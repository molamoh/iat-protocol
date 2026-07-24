"""Outcome registry and governed calibration for decision intelligence."""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from typing import Any

from iat.api.db import get_conn, qmark, release_conn


HASH_RE = re.compile(r"^[a-f0-9]{64}$")
OUTCOME_TYPES = {"success", "partial_success", "failure", "cancelled", "disputed"}


class DecisionOutcomeError(ValueError):
    pass


def _now() -> int:
    return int(time.time())


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _row(row) -> dict:
    item = dict(row)
    item["metadata"] = json.loads(item.get("metadata") or "{}")
    return item


def init_decision_outcome_table() -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS decision_outcomes (
                outcome_id TEXT PRIMARY KEY,
                decision_hash TEXT NOT NULL,
                outcome_key TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                outcome_type TEXT NOT NULL,
                predicted_utility REAL NOT NULL,
                observed_utility REAL NOT NULL,
                metadata TEXT NOT NULL,
                created_at BIGINT NOT NULL,
                UNIQUE(decision_hash, outcome_key)
            )"""
        )
        cur.execute(
            """CREATE INDEX IF NOT EXISTS idx_decision_outcomes_calibration
            ON decision_outcomes(decision_type, created_at)"""
        )
        conn.commit()
    finally:
        release_conn(conn)


def record_decision_outcome(
    *,
    decision_hash: str,
    outcome_key: str,
    decision_type: str,
    outcome_type: str,
    predicted_utility: float,
    observed_utility: float,
    metadata: dict | None = None,
) -> dict:
    init_decision_outcome_table()
    decision_hash = str(decision_hash or "").lower()
    if not HASH_RE.fullmatch(decision_hash):
        raise DecisionOutcomeError("invalid_decision_hash")
    outcome_key = str(outcome_key or "").strip()
    if not 8 <= len(outcome_key) <= 160:
        raise DecisionOutcomeError("invalid_outcome_key")
    if outcome_type not in OUTCOME_TYPES:
        raise DecisionOutcomeError("unsupported_outcome_type")
    decision_type = str(decision_type or "").strip()
    if not 3 <= len(decision_type) <= 80:
        raise DecisionOutcomeError("invalid_decision_type")
    try:
        predicted, observed = float(predicted_utility), float(observed_utility)
    except (TypeError, ValueError) as exc:
        raise DecisionOutcomeError("invalid_utility") from exc
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in (predicted, observed)):
        raise DecisionOutcomeError("utility_out_of_range")

    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(
            f"""SELECT * FROM decision_outcomes
            WHERE decision_hash={p} AND outcome_key={p}""",
            (decision_hash, outcome_key),
        )
        existing = cur.fetchone()
        if existing:
            item = _row(existing)
            same = (
                item["outcome_type"] == outcome_type
                and float(item["predicted_utility"]) == predicted
                and float(item["observed_utility"]) == observed
            )
            if not same:
                raise DecisionOutcomeError("outcome_idempotency_conflict")
            return {"status": "already_recorded", "outcome": item}
        outcome_id = f"iout_{uuid.uuid4().hex}"
        cur.execute(
            f"""INSERT INTO decision_outcomes
            (outcome_id, decision_hash, outcome_key, decision_type, outcome_type,
             predicted_utility, observed_utility, metadata, created_at)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p})""",
            (
                outcome_id, decision_hash, outcome_key, decision_type, outcome_type,
                predicted, observed, _json(metadata or {}), _now(),
            ),
        )
        conn.commit()
    finally:
        release_conn(conn)
    return {"status": "recorded", "outcome_id": outcome_id}


def list_decision_outcomes(*, decision_type: str | None = None, limit: int = 200) -> dict:
    init_decision_outcome_table()
    limit = max(1, min(int(limit), 1_000))
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        if decision_type:
            cur.execute(
                f"""SELECT * FROM decision_outcomes WHERE decision_type={p}
                ORDER BY created_at DESC LIMIT {limit}""",
                (decision_type,),
            )
        else:
            cur.execute(f"SELECT * FROM decision_outcomes ORDER BY created_at DESC LIMIT {limit}")
        items = [_row(row) for row in cur.fetchall()]
        return {"status": "ok", "count": len(items), "outcomes": items}
    finally:
        release_conn(conn)


def decision_calibration(*, decision_type: str | None = None, limit: int = 500) -> dict:
    items = list_decision_outcomes(decision_type=decision_type, limit=limit)["outcomes"]
    if not items:
        return {
            "status": "insufficient_data",
            "sample_size": 0,
            "minimum_recommended_samples": 20,
            "policy_mutation_allowed": False,
        }
    errors = [
        float(item["observed_utility"]) - float(item["predicted_utility"])
        for item in items
    ]
    mean_error = sum(errors) / len(errors)
    mean_absolute_error = sum(abs(value) for value in errors) / len(errors)
    enough = len(items) >= 20
    drift = enough and (abs(mean_error) >= .15 or mean_absolute_error >= .25)
    return {
        "status": "ok" if enough else "insufficient_data",
        "sample_size": len(items),
        "minimum_recommended_samples": 20,
        "calibration": {
            "mean_error": round(mean_error, 6),
            "mean_absolute_error": round(mean_absolute_error, 6),
            "direction": "overestimating" if mean_error < -.05 else (
                "underestimating" if mean_error > .05 else "calibrated"
            ),
        },
        "drift": {
            "detected": drift,
            "severity": "warning" if drift else "none",
        },
        "recommendation": (
            "review_policy_in_shadow_mode" if drift
            else "collect_more_outcomes" if not enough
            else "keep_current_policy"
        ),
        "policy_mutation_allowed": False,
    }
