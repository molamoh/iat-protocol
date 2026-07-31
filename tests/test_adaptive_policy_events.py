import json

import pytest

from iat.api import db


def test_adaptive_policy_event_matches_initialized_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "adaptive-events.sqlite")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    db.init_adaptive_defense_tables()

    result = db.record_adaptive_policy_event_db(
        "policy-1",
        "global",
        "research",
        "activated",
        old_policy={"risk_level": "low", "confidence": 0.4},
        new_policy={"risk_level": "high", "confidence": 0.9},
        reason={"signal": "canary"},
    )

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM adaptive_policy_events WHERE policy_id = ?",
            ("policy-1",),
        ).fetchone()
    finally:
        db.release_conn(conn)

    assert result == {
        "status": "policy_event_recorded",
        "policy_id": "policy-1",
        "event_type": "activated",
    }
    assert row["event_id"].startswith("ape_")
    assert json.loads(row["old_policy"])["risk_level"] == "low"
    assert json.loads(row["new_policy"])["risk_level"] == "high"
    assert json.loads(row["reason"]) == {"signal": "canary"}


def test_adaptive_policy_event_releases_connection_on_insert_failure(monkeypatch):
    class Cursor:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("insert failed")

    class Connection:
        rolled_back = False

        def cursor(self):
            return Cursor()

        def rollback(self):
            self.rolled_back = True

    conn = Connection()
    released = []
    monkeypatch.setattr(db, "get_conn", lambda: conn)
    monkeypatch.setattr(db, "release_conn", released.append)

    with pytest.raises(RuntimeError, match="insert failed"):
        db.record_adaptive_policy_event_db(
            "policy-1", "global", None, "activated"
        )

    assert conn.rolled_back is True
    assert released == [conn]
