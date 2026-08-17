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
    events = resumed.list_events("bid_1")
    assert [event["event_type"] for event in events["events"]] == ["scheduled"]


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


def test_jobs_can_be_filtered_and_explain_their_state(tmp_path):
    scheduler = BuyerAgentScheduler(Runner([]), tmp_path / "jobs.sqlite3")
    scheduler.schedule("bid_a", now=100)
    scheduler.schedule("bid_b", now=101)
    listed = scheduler.list_jobs(state="scheduled", limit=1)
    assert listed["total"] == 2
    assert listed["count"] == 1
    assert listed["next_offset"] == 1
    assert listed["jobs"][0]["reason_category"] == "in_progress"
    assert listed["jobs"][0]["recommended_action"] == "wait_for_scheduler"
    assert listed["jobs"][0]["recoverable"] is False


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
    events = scheduler.list_events("bid_1")["events"]
    assert [event["event_type"] for event in events] == [
        "scheduled",
        "attempt_started",
        "waiting",
    ]
    assert events[-1]["action"] == "confirm_payment"


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
    assert scheduler.list_events("bid_1")["events"][-1]["event_type"] == "completed"


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
    event = scheduler.list_events("bid_1")["events"][-1]
    assert event["event_type"] == "retry_scheduled"
    assert event["error"] == "iat_transport_failed"


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
    assert job["recoverable"] is True
    assert job["reason_category"] == "retry_budget_exhausted"


def test_exhausted_job_can_be_resumed_with_a_new_bounded_budget(tmp_path):
    runner = Runner([{"next_action": "wait_for_delivery"}])
    scheduler = BuyerAgentScheduler(runner, tmp_path / "jobs.sqlite3")
    scheduler.schedule("bid_1", now=100, max_attempts=1)
    scheduler.run_due_once(now=100)
    resumed = scheduler.resume("bid_1", additional_attempts=3, now=200)
    assert resumed["state"] == "scheduled"
    assert resumed["next_run_at"] == 200
    assert resumed["max_attempts"] == 4
    assert resumed["last_error"] is None
    assert resumed["recoverable"] is False
    assert scheduler.list_events("bid_1")["events"][-1]["event_type"] == "resumed"


def test_event_history_is_paginated_and_survives_restart(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    scheduler = BuyerAgentScheduler(
        Runner([{"next_action": "wait_for_delivery"}]),
        database,
    )
    scheduler.schedule("bid_1", now=100)
    scheduler.run_due_once(now=100)
    resumed = BuyerAgentScheduler(Runner([]), database)
    first_page = resumed.list_events("bid_1", limit=2)
    second_page = resumed.list_events("bid_1", limit=2, offset=2)
    assert first_page["total"] == 3
    assert first_page["next_offset"] == 2
    assert [event["event_type"] for event in second_page["events"]] == ["waiting"]


def test_security_stopped_job_cannot_be_resumed(tmp_path):
    runner = Runner([AutonomousBuyerError("transaction_fee_payer_mismatch")])
    scheduler = BuyerAgentScheduler(runner, tmp_path / "jobs.sqlite3")
    scheduler.schedule("bid_1", now=100)
    stopped = scheduler.run_due_once(now=100)[0]
    assert stopped["reason_category"] == "security_boundary"
    try:
        scheduler.resume("bid_1", now=200)
    except ValueError as exc:
        assert str(exc) == "buyer_agent_job_not_recoverable"
    else:
        raise AssertionError("security-stopped job was resumed")


def test_scheduler_database_contains_no_runner_credentials(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    runner = Runner([])
    runner.access_token = "secret-wallet-session-token"
    scheduler = BuyerAgentScheduler(runner, database)
    scheduler.schedule("bid_1", now=100)
    with sqlite3.connect(database) as connection:
        dump = "\n".join(connection.iterdump())
    assert runner.access_token not in dump
