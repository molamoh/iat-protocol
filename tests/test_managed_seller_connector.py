import importlib.util
from pathlib import Path

import pytest

from iat.api import agent_b_api, db
from iat.action_engine import protocol_runtime
from iat.security import connector_vault, network


MODULE_PATH = Path(__file__).parents[1] / "integrations" / "managed_seller_connector" / "connector.py"
SPEC = importlib.util.spec_from_file_location("managed_seller_connector", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/claim"):
            return Response({"status": "ok", "task": {"task_id": "sct_1", "lease_token": "isl_token", "request_payload": {"request": "work"}}})
        if url == "https://agent.local/execute":
            return Response({"status": "success", "answer": "done"})
        return Response({"status": "ok", "result_pending_protocol_verification": True})


def test_connector_keeps_lease_and_connector_credentials_out_of_agent_payload(monkeypatch):
    monkeypatch.setattr(MODULE, "CONNECTOR_KEY", "isc_test")
    monkeypatch.setattr(MODULE, "AGENT_URL", "https://agent.local/execute")
    monkeypatch.setattr(MODULE, "AGENT_SECRET", "agent-secret")
    session = Session()
    result = MODULE.process_once(session=session)
    agent_call = session.calls[1]
    completion_call = session.calls[2]
    assert agent_call[1]["json"] == {"request": "work"}
    assert agent_call[1]["headers"]["Authorization"] == "Bearer agent-secret"
    assert "X-IAT-Connector-Key" not in agent_call[1]["headers"]
    assert completion_call[1]["json"]["lease_token"] == "isl_token"
    assert result["result_pending_protocol_verification"] is True


def connector_database(tmp_path, monkeypatch):
    database = tmp_path / "connector.sqlite"
    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    db.init_seller_connector_tables()
    return database


def test_order_enqueue_is_idempotent(tmp_path, monkeypatch):
    connector_database(tmp_path, monkeypatch)
    first = db.enqueue_seller_connector_task_db(
        "seller_1", {"task": "safe"}, order_reference="order_1"
    )
    replay = db.enqueue_seller_connector_task_db(
        "seller_1", {"task": "different"}, order_reference="order_1"
    )
    assert replay["task_id"] == first["task_id"]
    assert replay["idempotent_replay"] is True
    assert db.get_seller_connector_task_db(order_reference="order_1")["request_payload"] == {"task": "safe"}


def test_expired_lease_cannot_complete_and_task_can_be_reclaimed(tmp_path, monkeypatch):
    connector_database(tmp_path, monkeypatch)
    queued = db.enqueue_seller_connector_task_db("seller_1", {"task": "safe"})
    first = db.claim_seller_connector_task_db("seller_1", "lease_old", now=100, lease_seconds=15)
    rejected = db.complete_seller_connector_task_db(
        "seller_1", queued["task_id"], "lease_old", {"answer": "late"}, now=116
    )
    second = db.claim_seller_connector_task_db("seller_1", "lease_new", now=116, lease_seconds=15)
    assert first["task"]["task_id"] == queued["task_id"]
    assert rejected["message"] == "connector_task_lease_invalid_or_expired"
    assert second["task"]["task_id"] == queued["task_id"]
    assert second["task"]["attempt_count"] == 2


def test_paid_order_queue_requires_verified_active_seller_and_strips_buyer_data(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent_b_api, "get_agent_db", lambda _agent_id: {
        "agent_type": "seller",
        "seller_status": "active",
        "verification_status": "foundation_verified",
        "available": True,
        "seller_id": "seller_1",
        "seller_agent_id": "seller_agent_1",
    })
    monkeypatch.setattr(agent_b_api, "seller_connector_available_db", lambda _seller_id: True)
    monkeypatch.setattr(
        agent_b_api,
        "enqueue_seller_connector_task_db",
        lambda **kwargs: captured.update(kwargs) or {"status": "ok", "task_id": "sct_1"},
    )
    monkeypatch.setattr(agent_b_api, "update_order_db", lambda *_args, **_kwargs: None)
    result = agent_b_api.queue_paid_order_for_managed_connector({
        "order_id": "order_1",
        "seller_id": "agent_1",
        "service": "research",
        "query": "safe task",
        "buyer_context": {"wallet": "must-not-leak"},
        "buyer_wallet": "must-not-leak",
    }, "tx_1")
    serialized = str(captured["request_payload"])
    assert result["status"] == "seller_execution_pending"
    assert "must-not-leak" not in serialized
    assert captured["order_reference"] == "order_1"


def test_paid_order_queue_rejects_unverified_seller(monkeypatch):
    monkeypatch.setattr(agent_b_api, "get_agent_db", lambda _agent_id: {
        "agent_type": "seller",
        "seller_status": "active",
        "verification_status": "unverified",
        "available": True,
        "seller_id": "seller_1",
        "seller_agent_id": "seller_agent_1",
    })
    monkeypatch.setattr(
        agent_b_api,
        "enqueue_seller_connector_task_db",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not enqueue")),
    )
    assert agent_b_api.queue_paid_order_for_managed_connector(
        {"order_id": "order_1", "seller_id": "agent_1"}, "tx_1"
    ) is None


def test_foundation_pipeline_reuses_verified_connector_contribution(monkeypatch):
    monkeypatch.setattr(
        protocol_runtime,
        "get_latest_verified_seller_execution_session_db",
        lambda _order_id: {
            "execution_session_id": "exec_connector_1",
            "execution_status": "verified",
            "execution_result": '{"status":"ok","execution_mode":"managed_connector"}',
            "verification_result": '{"verification_status":"approved"}',
        },
    )
    monkeypatch.setattr(
        protocol_runtime,
        "run_foundation_controlled_seller_execution_db",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not execute twice")),
    )
    monkeypatch.setattr(
        protocol_runtime,
        "run_foundation_decision_db",
        lambda _order_id: {
            "foundation_decision": {
                "foundation_verdict": "pending",
                "foundation_evidence_evaluation": {"foundation_decision_ready": False},
            }
        },
    )
    result = protocol_runtime.run_foundation_supplier_pipeline({
        "order_id": "order_1",
        "service": "research",
        "query": "safe task",
    })
    assert result["status"] == "foundation_review_required"
    assert result["supplier_execution"]["reused_verified_contribution"] is True
    assert result["supplier_verification"]["verification_status"] == "approved"


def test_seller_can_create_private_idempotent_canary(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent_b_api, "get_authenticated_seller_from_credentials", lambda *_args: {
        "seller_id": "seller_1", "email_verified": 1, "wallet_verified": 1
    })
    monkeypatch.setattr(agent_b_api, "seller_connector_available_db", lambda _seller_id: True)
    monkeypatch.setattr(agent_b_api.time, "time", lambda: 1501)
    monkeypatch.setattr(
        agent_b_api,
        "enqueue_seller_connector_task_db",
        lambda *args, **kwargs: captured.update({"args": args, "kwargs": kwargs}) or {
            "status": "ok", "task_id": "sct_canary", "idempotent_replay": False
        },
    )
    result = agent_b_api.seller_connector_canary("seller-key", None)
    assert result["task_id"] == "sct_canary"
    assert captured["kwargs"]["order_reference"] == "connector_canary:seller_1:5"
    assert captured["args"][1]["buyer_context_included"] is False
    assert captured["args"][1]["payment_context_included"] is False


def test_canary_completion_does_not_enter_order_governance(monkeypatch):
    monkeypatch.setattr(agent_b_api, "authenticated_connector_seller", lambda _key: {"seller_id": "seller_1"})
    monkeypatch.setattr(
        agent_b_api,
        "complete_seller_connector_task_db",
        lambda *_args: {"status": "ok", "task_id": "sct_canary"},
    )
    monkeypatch.setattr(
        agent_b_api,
        "get_seller_connector_task_db",
        lambda **_kwargs: {"request_payload": {"type": "canary"}},
    )
    monkeypatch.setattr(
        agent_b_api,
        "verify_completed_seller_connector_task_db",
        lambda _task_id: (_ for _ in ()).throw(AssertionError("canary is not an order")),
    )
    request = agent_b_api.SellerConnectorResultRequest(
        lease_token="isl_" + "x" * 40,
        result={"status": "ok"},
    )
    result = agent_b_api.seller_connector_task_complete(
        "sct_canary", request, "isc_test"
    )
    assert result["canary_completed"] is True


def test_seller_can_only_read_own_connector_task_status(monkeypatch):
    monkeypatch.setattr(
        agent_b_api,
        "get_authenticated_seller_from_credentials",
        lambda *_args: {"seller_id": "seller_1"},
    )
    monkeypatch.setattr(
        agent_b_api,
        "get_seller_connector_task_db",
        lambda **_kwargs: {
            "seller_id": "seller_1",
            "status": "completed",
            "attempt_count": 1,
            "request_payload": {"type": "canary"},
            "result_payload": {"private": "must-not-be-returned"},
        },
    )
    result = agent_b_api.seller_connector_task_status(
        "sct_canary", "seller-key", None
    )
    assert result == {
        "status": "ok",
        "task_id": "sct_canary",
        "task_status": "completed",
        "attempt_count": 1,
        "completed": True,
        "canary": True,
    }


def test_seller_cannot_read_another_sellers_connector_task(monkeypatch):
    monkeypatch.setattr(
        agent_b_api,
        "get_authenticated_seller_from_credentials",
        lambda *_args: {"seller_id": "seller_1"},
    )
    monkeypatch.setattr(
        agent_b_api,
        "get_seller_connector_task_db",
        lambda **_kwargs: {"seller_id": "seller_2", "status": "completed"},
    )
    try:
        agent_b_api.seller_connector_task_status("sct_other", "seller-key", None)
        raise AssertionError("cross-seller task read must fail")
    except agent_b_api.HTTPException as exc:
        assert exc.status_code == 404


def test_hosted_connector_secret_is_encrypted_and_bound_to_seller(monkeypatch):
    monkeypatch.setenv("IAT_ADMIN_API_KEY", "admin-secret-long-enough-for-vault")
    encrypted = connector_vault.encrypt_connector_secret("seller_1", "agent-token")
    assert encrypted != "agent-token"
    assert connector_vault.decrypt_connector_secret("seller_1", encrypted) == "agent-token"
    with pytest.raises(Exception):
        connector_vault.decrypt_connector_secret("seller_2", encrypted)


def test_hosted_connector_calls_agent_without_platform_credentials(monkeypatch):
    monkeypatch.setenv("IAT_ADMIN_API_KEY", "admin-secret-long-enough-for-vault")
    monkeypatch.setattr(network, "validate_public_runtime_url", lambda _url: {"public": True})
    captured = {}

    class HostedResponse:
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            assert chunk_size == 8192
            yield b'{"status":"ok"}'

    def hosted_post(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return HostedResponse()

    monkeypatch.setattr(agent_b_api.requests, "post", hosted_post)
    encrypted = connector_vault.encrypt_connector_secret("seller_1", "agent-token")
    result = agent_b_api._execute_hosted_connector_task(
        {
            "seller_id": "seller_1",
            "execution_mode": "external_endpoint",
            "agent_url": "https://agent.example/execute",
            "agent_secret_encrypted": encrypted,
        },
        {"request_payload": {"type": "canary", "buyer_context_included": False}},
    )
    assert result == {"status": "ok"}
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer agent-token"
    assert "IAT_ADMIN_API_KEY" not in str(captured)
    assert captured["kwargs"]["allow_redirects"] is False
    assert captured["kwargs"]["stream"] is True


def test_hosted_connector_configuration_never_returns_secret(monkeypatch):
    monkeypatch.setenv("IAT_ADMIN_API_KEY", "admin-secret-long-enough-for-vault")
    monkeypatch.setattr(agent_b_api, "get_authenticated_seller_from_credentials", lambda *_args: {
        "seller_id": "seller_1", "email_verified": 1, "wallet_verified": 1
    })
    monkeypatch.setattr(network, "validate_public_runtime_url", lambda _url: {"public": True})
    stored = {}
    monkeypatch.setattr(
        agent_b_api,
        "store_seller_hosted_connector_config_db",
        lambda seller_id, agent_url, encrypted_secret, execution_mode: stored.update(
            seller_id=seller_id, agent_url=agent_url, encrypted_secret=encrypted_secret,
            execution_mode=execution_mode,
        ) or {"status": "ok", "seller_id": seller_id, "agent_url": agent_url},
    )
    request = agent_b_api.SellerHostedConnectorRequest(
        execution_mode="external_endpoint",
        agent_url="https://agent.example/execute", agent_secret="agent-token"
    )
    result = agent_b_api.seller_hosted_connector_configure(
        request, "seller-key", None
    )
    assert result["secret_stored"] is True
    assert result["secret_returned"] is False
    assert "agent-token" not in str(result)
    assert stored["encrypted_secret"] != "agent-token"


def test_iat_hosted_runtime_requires_no_url_or_secret(monkeypatch):
    monkeypatch.setattr(agent_b_api, "get_authenticated_seller_from_credentials", lambda *_args: {
        "seller_id": "seller_1", "email_verified": 1, "wallet_verified": 1
    })
    stored = {}
    monkeypatch.setattr(
        agent_b_api,
        "store_seller_hosted_connector_config_db",
        lambda seller_id, agent_url, encrypted_secret, execution_mode: stored.update(
            seller_id=seller_id, agent_url=agent_url, encrypted_secret=encrypted_secret,
            execution_mode=execution_mode,
        ) or {"status": "ok", "seller_id": seller_id},
    )
    result = agent_b_api.seller_hosted_connector_configure(
        agent_b_api.SellerHostedConnectorRequest(execution_mode="iat_hosted"),
        "seller-key",
        None,
    )
    assert result["status"] == "ok"
    assert stored == {
        "seller_id": "seller_1",
        "agent_url": "",
        "encrypted_secret": None,
        "execution_mode": "iat_hosted",
    }


def test_iat_hosted_canary_executes_without_network(monkeypatch):
    monkeypatch.setattr(
        agent_b_api.requests,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network not allowed")),
    )
    result = agent_b_api._execute_hosted_connector_task(
        {"seller_id": "seller_1", "execution_mode": "iat_hosted"},
        {"request_payload": {"type": "canary"}},
    )
    assert result == {
        "status": "ok",
        "execution_mode": "iat_hosted",
        "canary": True,
        "seller_id": "seller_1",
    }
