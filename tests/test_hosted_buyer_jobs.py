import pytest

from iat.api import db
from iat.hosted_buyer_jobs import (
    claim_hosted_buyer_job,
    enqueue_hosted_buyer_job,
    finish_hosted_buyer_job,
)
from iat.hosted_buyer_registry import register_hosted_buyer_agent


@pytest.fixture()
def jobs_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "hosted-jobs.sqlite")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    db.init_db()


WALLET = "BSNCPxSJZqgo34xf2JfCjQ83JcuQgzs6sqAziNYyQU3Q"


def test_job_enqueue_claim_and_finish_are_idempotent(jobs_database):
    agent = register_hosted_buyer_agent(
        buyer_wallet=WALLET, runtime_connector_id="connector-jobs", now=100
    )
    first = enqueue_hosted_buyer_job(
        buyer_agent_id=agent["buyer_agent_id"],
        intent_decision_id="intent-1",
        payload={"service": "research"},
        now=100,
    )
    replay = enqueue_hosted_buyer_job(
        buyer_agent_id=agent["buyer_agent_id"],
        intent_decision_id="intent-1",
        payload={"service": "changed"},
        now=101,
    )
    assert replay["job_id"] == first["job_id"]
    assert replay["idempotent_replay"] is True
    claimed = claim_hosted_buyer_job(now=100)
    assert claimed["state"] == "leased"
    finished = finish_hosted_buyer_job(
        job_id=claimed["job_id"],
        lease_token=claimed["lease_token"],
        state="completed",
        action="delivery_verified",
        now=120,
    )
    assert finished["state"] == "completed"
    assert claim_hosted_buyer_job(now=121)["status"] == "empty"


def test_expired_lease_is_recoverable(jobs_database):
    agent = register_hosted_buyer_agent(
        buyer_wallet=WALLET, runtime_connector_id="connector-recovery", now=100
    )
    enqueue_hosted_buyer_job(
        buyer_agent_id=agent["buyer_agent_id"], intent_decision_id="intent-2", now=100
    )
    first = claim_hosted_buyer_job(now=100, lease_seconds=15)
    recovered = claim_hosted_buyer_job(now=116, lease_seconds=15)
    assert first["job_id"] == recovered["job_id"]
    assert recovered["attempt_count"] == 2


def test_lease_token_is_required_to_finish(jobs_database):
    agent = register_hosted_buyer_agent(
        buyer_wallet=WALLET, runtime_connector_id="connector-lease", now=100
    )
    enqueue_hosted_buyer_job(
        buyer_agent_id=agent["buyer_agent_id"], intent_decision_id="intent-3", now=100
    )
    claimed = claim_hosted_buyer_job(now=100)
    result = finish_hosted_buyer_job(
        job_id=claimed["job_id"], lease_token="wrong", state="completed", now=110
    )
    assert result["status"] == "lease_conflict"
