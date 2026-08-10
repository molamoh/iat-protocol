import importlib.util
from pathlib import Path


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
