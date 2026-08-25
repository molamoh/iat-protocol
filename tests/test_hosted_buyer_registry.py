import pytest

from iat.api import db
from iat.hosted_buyer_registry import (
    heartbeat_hosted_buyer_agent,
    register_hosted_buyer_agent,
)


@pytest.fixture()
def registry_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "hosted-buyers.sqlite")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    db.init_db()


WALLET = "BSNCPxSJZqgo34xf2JfCjQ83JcuQgzs6sqAziNYyQU3Q"


def test_registration_is_idempotent_and_never_returns_secrets(registry_database):
    first = register_hosted_buyer_agent(
        buyer_wallet=WALLET,
        runtime_connector_id="connector-buyer-1",
        policy={"max_per_order_minor": 2_000_000},
        now=100,
    )
    replay = register_hosted_buyer_agent(
        buyer_wallet=WALLET,
        runtime_connector_id="connector-buyer-1",
        policy={"max_per_order_minor": 999},
        now=200,
    )
    assert first["buyer_agent_id"].startswith("bya_")
    assert replay["buyer_agent_id"] == first["buyer_agent_id"]
    assert replay["policy"] == {"max_per_order_minor": 2_000_000}
    assert "token" not in replay
    assert "private_key" not in replay


def test_heartbeat_updates_only_public_runtime_state(registry_database):
    created = register_hosted_buyer_agent(
        buyer_wallet=WALLET,
        runtime_connector_id="connector-buyer-2",
        now=100,
    )
    updated = heartbeat_hosted_buyer_agent(
        created["buyer_agent_id"], status="active", now=120
    )
    assert updated["last_heartbeat_at"] == 120
    assert updated["status"] == "active"


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"buyer_wallet": "not-a-wallet", "runtime_connector_id": "x"}, "buyer_wallet_invalid"),
        ({"buyer_wallet": WALLET, "runtime_connector_id": "x"}, "runtime_connector_id_invalid"),
        ({"buyer_wallet": WALLET, "runtime_connector_id": "connector", "cluster": "solana:mainnet"}, "buyer_cluster_not_allowed"),
    ],
)
def test_registry_rejects_unsafe_runtime_metadata(registry_database, kwargs, error):
    with pytest.raises(ValueError, match=error):
        register_hosted_buyer_agent(**kwargs)
