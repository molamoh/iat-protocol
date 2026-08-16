import sqlite3

from iat.autonomous_buyer import AutonomousBuyerError
from iat.buyer_agent_scheduler import BuyerAgentScheduler


class Runner:
    def __init__(self, lifecycles, steps=None, results=None):
        self.lifecycles = list(lifecycles)
        self.steps = list(steps or [])
        self.results = list(results or [])
        self.calls = []

    def lifecycle(self, decision_id):
        self.calls.append(("lifecycle", decision_id))
        value = self.lifecycles.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def step(self, decision_id):
        self.calls.append(("step", decision_id))
        value = self.steps.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def open_result(self, decision_id):
        self.calls.append(("result", decision_id))
        return self.results.pop(0)


def test_schedule_is_idempotent_and_survives_restart(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    first = BuyerAgentScheduler(Runner([]), database)
    first.schedule("bid_1", now=100, max_attempts=7)
    first.schedule("bid_1", now=200, max_attempts=99)
    resumed = BuyerAgentScheduler(Runner([]), database)
    job = resumed.get("bid_1")
    assert job["state"] == "scheduled"
    assert job["next_run_at"] == 100
    assert job["max_attempts"] == 7


def test_summary_exposes_counts_without_job_contents(tmp_path):
    scheduler = BuyerAgentScheduler(Runner([]), tmp_path / "jobs.sqlite3")
    scheduler.schedule("bid_due", now=100)
    scheduler.schedule("bid_later", now=200)
    summary = scheduler.summary(now=150)
    assert summary == {
        "status": "ready",
        "due_jobs": 1,
        "next_due_at": 100,
        "states": {"scheduled": 2},
        "total_jobs": 2,
    }


def test_cycle_performs_only_one_transition_and_respects_poll_delay(tmp_path):
    runner = Runner(
        [{"next_action": "confirm_payment"}],
        [{"status": "buyer_intent_confirmation_pending", "poll_after_seconds": 17}],
    )
    scheduler = BuyerAgentScheduler(runner, tmp_path / "jobs.sqlite3")
    scheduler.schedule("bid_1", now=100)
    jobs = scheduler.run_due_once(now=100)
    assert [call[0] for call in runner.calls] == ["lifecycle", "step"]
    assert jobs[0]["state"] == "waiting"
    assert jobs[0]["next_run_at"] == 117
    assert scheduler.run_due_once(now=116) == []


def test_ready_delivery_is_opened_once_and_job_completes(tmp_path):
    runner = Runner(
        [{"next_action": "open_delivery_inbox"}],
        results=[{"status": "wallet_inbox_item_opened"}],
    )
    scheduler = BuyerAgentScheduler(runner, tmp_path / "jobs.sqlite3")
    scheduler.schedule("bid_1", now=100)
    job = scheduler.run_due_once(now=100)[0]
    assert job["state"] == "completed"
    assert scheduler.run_due_once(now=1_000) == []
    assert [call[0] for call in runner.calls] == ["lifecycle", "result"]


def test_security_error_stops_without_retry(tmp_path):
    runner = Runner([AutonomousBuyerError("transaction_fee_payer_mismatch")])
    scheduler = BuyerAgentScheduler(runner, tmp_path / "jobs.sqlite3")
    scheduler.schedule("bid_1", now=100)
    job = scheduler.run_due_once(now=100)[0]
    assert job["state"] == "stopped"
    assert job["last_error"] == "transaction_fee_payer_mismatch"
    assert scheduler.run_due_once(now=1_000) == []


def test_transport_error_retries_with_bounded_backoff(tmp_path):
    runner = Runner([AutonomousBuyerError("iat_transport_failed")])
    scheduler = BuyerAgentScheduler(runner, tmp_path / "jobs.sqlite3")
    scheduler.schedule("bid_1", now=100, max_attempts=2)
    job = scheduler.run_due_once(now=100)[0]
    assert job["state"] == "waiting"
    assert job["next_run_at"] == 105
    assert job["last_error"] == "iat_transport_failed"


def test_job_stops_as_soon_as_attempt_budget_is_exhausted(tmp_path):
    runner = Runner(
        [{"next_action": "wait_for_delivery", "poll_after_seconds": 10}],
    )
    scheduler = BuyerAgentScheduler(runner, tmp_path / "jobs.sqlite3")
    scheduler.schedule("bid_1", now=100, max_attempts=1)
    job = scheduler.run_due_once(now=100)[0]
    assert job["state"] == "stopped"
    assert job["attempt_count"] == 1
    assert job["last_error"] == "maximum_attempts_reached"


def test_scheduler_database_contains_no_runner_credentials(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    runner = Runner([])
    runner.access_token = "secret-wallet-session-token"
    scheduler = BuyerAgentScheduler(runner, database)
    scheduler.schedule("bid_1", now=100)
    with sqlite3.connect(database) as connection:
        dump = "\n".join(connection.iterdump())
    assert runner.access_token not in dump
