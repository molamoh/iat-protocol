import sqlite3

import pytest

import iat.intelligence.decision_learning as learning


@pytest.fixture()
def outcome_db(tmp_path, monkeypatch):
    database = tmp_path / "decision-outcomes.db"

    def connect():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(learning, "get_conn", connect)
    monkeypatch.setattr(learning, "release_conn", lambda conn: conn.close())
    monkeypatch.setattr(learning, "qmark", lambda: "?")
    learning.init_decision_outcome_table()
    return database


def _record(index=1, **overrides):
    payload = {
        "decision_hash": f"{index:064x}",
        "outcome_key": f"order-outcome-{index:04d}",
        "decision_type": "select_offer",
        "outcome_type": "success",
        "predicted_utility": .8,
        "observed_utility": .9,
        "metadata": {"order_id": f"order-{index}"},
    }
    payload.update(overrides)
    return learning.record_decision_outcome(**payload)


def test_outcome_recording_is_idempotent(outcome_db):
    first = _record()
    second = _record()

    assert first["status"] == "recorded"
    assert second["status"] == "already_recorded"
    assert learning.list_decision_outcomes()["count"] == 1


def test_outcome_idempotency_conflict_fails_closed(outcome_db):
    _record()

    with pytest.raises(learning.DecisionOutcomeError, match="conflict"):
        _record(observed_utility=.1)


def test_calibration_detects_sustained_overestimation_without_mutating_policy(outcome_db):
    for index in range(1, 21):
        _record(index, predicted_utility=.9, observed_utility=.2, outcome_type="failure")

    report = learning.decision_calibration(decision_type="select_offer")

    assert report["status"] == "ok"
    assert report["drift"]["detected"] is True
    assert report["calibration"]["direction"] == "overestimating"
    assert report["recommendation"] == "review_policy_in_shadow_mode"
    assert report["policy_mutation_allowed"] is False


def test_invalid_hash_and_utility_are_rejected(outcome_db):
    with pytest.raises(learning.DecisionOutcomeError, match="invalid_decision_hash"):
        _record(decision_hash="not-a-hash")

    with pytest.raises(learning.DecisionOutcomeError, match="utility_out_of_range"):
        _record(predicted_utility=1.1)
