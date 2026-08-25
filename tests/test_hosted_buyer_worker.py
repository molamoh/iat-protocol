import pytest

from iat.api import db
from iat.hosted_buyer_jobs import enqueue_hosted_buyer_job, init_hosted_buyer_jobs_db
from iat.hosted_buyer_registry import register_hosted_buyer_agent
from iat.hosted_buyer_worker import HostedBuyerWorker


WALLET = "BSNCPxSJZqgo34xf2JfCjQ83JcuQgzs6sqAziNYyQU3Q"


class FakeRunner:
    def __init__(self, action="advance"):
        self.action = action

    def lifecycle(self, _decision_id):
        return {"next_action": self.action, "poll_after_seconds": 7}

    def step(self, _decision_id):
        return {"status": "buyer_transition_waiting", "poll_after_seconds": 9}


class Resolver:
    def __init__(self, runner):
        self.runner = runner

    def resolve(self, _buyer_agent_id):
        return self.runner


@pytest.fixture()
def hosted_database(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "hosted.db")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    db.init_db()


def setup_db():
    agent = register_hosted_buyer_agent(
        buyer_wallet=WALLET, runtime_connector_id="connector-test", now=100
    )
    init_hosted_buyer_jobs_db()
    job = enqueue_hosted_buyer_job(
        buyer_agent_id=agent["buyer_agent_id"], intent_decision_id="intent-1", now=100
    )
    return job


def test_worker_claims_one_transition_and_waits(hosted_database):
    job = setup_db()
    result = HostedBuyerWorker(Resolver(FakeRunner()), default_poll_seconds=5).run_once(now=100)
    assert result["state"] == "waiting"
    assert result["job_id"] == job["job_id"]


def test_worker_completes_delivery(hosted_database):
    job = setup_db()

    class Delivered(FakeRunner):
        def lifecycle(self, _decision_id):
            return {"next_action": "open_delivery_inbox"}

        def open_result(self, _decision_id):
            return {"status": "buyer_result_ready"}

    result = HostedBuyerWorker(Resolver(Delivered())).run_once(now=100)
    assert result["state"] == "completed"
    assert result["job_id"] == job["job_id"]
