import os
import time

import requests


API_ORIGIN = os.getenv("IAT_API_ORIGIN", "https://iat-protocol-latest.onrender.com").rstrip("/")
CONNECTOR_KEY = os.getenv("IAT_CONNECTOR_KEY", "").strip()
AGENT_URL = os.getenv("IAT_AGENT_URL", "").strip()
AGENT_SECRET = os.getenv("IAT_AGENT_SECRET", "").strip()


def require_configuration():
    missing = [name for name, value in (("IAT_CONNECTOR_KEY", CONNECTOR_KEY), ("IAT_AGENT_URL", AGENT_URL)) if not value]
    if missing:
        raise RuntimeError("missing_configuration:" + ",".join(missing))


def connector_headers():
    return {"X-IAT-Connector-Key": CONNECTOR_KEY, "Content-Type": "application/json"}


def process_once(session=requests):
    require_configuration()
    claimed = session.post(f"{API_ORIGIN}/seller/connector/tasks/claim", headers=connector_headers(), timeout=20)
    claimed.raise_for_status()
    envelope = claimed.json()
    if envelope.get("status") == "empty":
        return {"status": "empty"}
    task = envelope.get("task") or {}
    task_id = task.get("task_id")
    lease_token = task.get("lease_token")
    if not task_id or not lease_token:
        raise RuntimeError("invalid_claim_response")
    execution_headers = {"Content-Type": "application/json"}
    if AGENT_SECRET:
        execution_headers["Authorization"] = f"Bearer {AGENT_SECRET}"
    response = session.post(
        AGENT_URL,
        headers=execution_headers,
        json=task.get("request_payload") or {},
        timeout=45,
    )
    response.raise_for_status()
    result = response.json()
    completed = session.post(
        f"{API_ORIGIN}/seller/connector/tasks/{task_id}/complete",
        headers=connector_headers(),
        json={"lease_token": lease_token, "result": result},
        timeout=20,
    )
    completed.raise_for_status()
    return completed.json()


def run():
    require_configuration()
    while True:
        try:
            outcome = process_once()
            time.sleep(5 if outcome.get("status") == "empty" else 1)
        except Exception as exc:
            print(f"connector_error:{type(exc).__name__}:{str(exc)[:240]}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    run()
