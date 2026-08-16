import asyncio

import httpx

from iat.buyer_agent_scheduler import BuyerAgentScheduler
from iat.buyer_agent_service import create_buyer_agent_service


TOKEN = "buyer-agent-api-token-long-enough"


class Wallet:
    wallet_address = "wallet-public-address"


class Policy:
    allowed_clusters = ("solana:devnet",)


class Runner:
    wallet = Wallet()
    policy = Policy()

    def __init__(self):
        self.calls = []

    def create_intent(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"status": "buyer_intent_created", "intent_decision_id": "bid_1"}

    def step(self, decision_id):
        self.calls.append(("advance", decision_id))
        return {"status": "buyer_intent_waiting", "next_action": "wait_for_delivery"}

    def lifecycle(self, decision_id):
        self.calls.append(("lifecycle", decision_id))
        return {"status": "buyer_intent_lifecycle_found", "next_action": "wait_for_delivery"}

    def open_result(self, decision_id):
        self.calls.append(("result", decision_id))
        return {"status": "wallet_inbox_item_opened", "inbox": {"result": "done"}}


def call(app, method, path, **kwargs):
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://buyer-agent") as api:
            return await api.request(method, path, **kwargs)

    return asyncio.run(request())


def headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_buyer_agent_api_exposes_bounded_complete_journey():
    runner = Runner()
    app = create_buyer_agent_service(runner, service_token=TOKEN)
    created = call(
        app,
        "POST",
        "/v1/intents",
        headers=headers(),
        json={
            "service": "web_research",
            "goal": "Produce a cited autonomous market report",
            "maximum_price": 2,
            "idempotency_key": "buyer-intent-0001",
        },
    )
    advanced = call(app, "POST", "/v1/intents/bid_1/advance", headers=headers())
    lifecycle = call(app, "GET", "/v1/intents/bid_1", headers=headers())
    result = call(app, "GET", "/v1/intents/bid_1/result", headers=headers())
    assert created.status_code == advanced.status_code == lifecycle.status_code == result.status_code == 200
    assert [item[0] for item in runner.calls] == ["create", "advance", "lifecycle", "result"]
    assert result.json()["inbox"]["result"] == "done"


def test_buyer_agent_api_rejects_unauthenticated_mutation():
    runner = Runner()
    app = create_buyer_agent_service(runner, service_token=TOKEN)
    response = call(
        app,
        "POST",
        "/v1/intents",
        json={
            "service": "web_research",
            "goal": "Produce a cited autonomous market report",
            "maximum_price": 2,
            "idempotency_key": "buyer-intent-0001",
        },
    )
    assert response.status_code == 401
    assert runner.calls == []


def test_buyer_agent_health_contains_no_secret():
    app = create_buyer_agent_service(Runner(), service_token=TOKEN)
    body = call(app, "GET", "/health").json()
    assert body["private_key_configured"] is False
    assert TOKEN not in str(body)


def test_buyer_agent_api_schedules_and_runs_one_persistent_cycle(tmp_path):
    runner = Runner()
    scheduler = BuyerAgentScheduler(runner, tmp_path / "jobs.sqlite3")
    app = create_buyer_agent_service(runner, service_token=TOKEN, scheduler=scheduler)
    scheduled = call(
        app,
        "POST",
        "/v1/intents/bid_1/schedule",
        headers=headers(),
        json={"max_attempts": 5},
    )
    cycle = call(
        app,
        "POST",
        "/v1/scheduler/run-once",
        headers=headers(),
        json={"limit": 1},
    )
    job = call(app, "GET", "/v1/jobs/bid_1", headers=headers())
    assert scheduled.status_code == cycle.status_code == job.status_code == 200
    assert cycle.json()["processed"] == 1
    assert job.json()["state"] == "waiting"
    assert [item[0] for item in runner.calls] == ["lifecycle"]
