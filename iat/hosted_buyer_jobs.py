"""Shared, leased queue for hosted buyer orchestration."""

from __future__ import annotations

import json
import hashlib
import secrets
import time
import uuid
from typing import Any

from iat.api import db
from iat.hosted_buyer_registry import init_hosted_buyer_registry_db

GENESIS_EVENT_HASH = "0" * 64


def init_hosted_buyer_jobs_db() -> None:
    init_hosted_buyer_registry_db()
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS hosted_buyer_jobs (
                job_id TEXT PRIMARY KEY,
                buyer_agent_id TEXT NOT NULL,
                intent_decision_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued',
                next_run_at INTEGER NOT NULL,
                lease_token TEXT,
                lease_until INTEGER,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 100,
                last_action TEXT,
                last_error TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                completed_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS hosted_buyer_job_events (
                event_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                buyer_agent_id TEXT NOT NULL,
                intent_decision_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                state TEXT NOT NULL,
                action TEXT,
                error TEXT,
                created_at INTEGER NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """CREATE INDEX IF NOT EXISTS idx_hosted_buyer_job_events_job
               ON hosted_buyer_job_events(job_id, created_at, event_id)"""
        )
        cur.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_hosted_buyer_job_identity
               ON hosted_buyer_jobs(buyer_agent_id, intent_decision_id)"""
        )
        cur.execute(
            """CREATE INDEX IF NOT EXISTS idx_hosted_buyer_job_claim
               ON hosted_buyer_jobs(state, next_run_at, lease_until)"""
        )
        conn.commit()
    finally:
        db.release_conn(conn)


def enqueue_hosted_buyer_job(
    *,
    buyer_agent_id: str,
    intent_decision_id: str,
    payload: dict[str, Any] | None = None,
    max_attempts: int = 100,
    now: int | None = None,
) -> dict[str, Any]:
    if not buyer_agent_id or not intent_decision_id:
        raise ValueError("buyer_job_identity_required")
    if not 1 <= int(max_attempts) <= 10_000:
        raise ValueError("buyer_job_max_attempts_invalid")
    current = int(time.time()) if now is None else int(now)
    init_hosted_buyer_jobs_db()
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"""SELECT * FROM hosted_buyer_jobs
                WHERE buyer_agent_id={p} AND intent_decision_id={p}""",
            (buyer_agent_id, intent_decision_id),
        )
        existing = cur.fetchone()
        if existing:
            return _public(dict(existing), idempotent=True)
        job_id = "hbj_" + uuid.uuid4().hex
        cur.execute(
            f"""INSERT INTO hosted_buyer_jobs (
                job_id, buyer_agent_id, intent_decision_id, state,
                next_run_at, attempt_count, max_attempts, payload_json,
                created_at, updated_at
            ) VALUES ({p},{p},{p},'queued',{p},0,{p},{p},{p},{p})""",
            (
                job_id,
                buyer_agent_id,
                intent_decision_id,
                current,
                int(max_attempts),
                json.dumps(payload or {}, sort_keys=True, separators=(",", ":")),
                current,
                current,
            ),
        )
        _record_event(
            cur, job_id=job_id, buyer_agent_id=buyer_agent_id,
            intent_decision_id=intent_decision_id, event_type="queued",
            state="queued", created_at=current,
        )
        conn.commit()
        cur.execute(f"SELECT * FROM hosted_buyer_jobs WHERE job_id={p}", (job_id,))
        return _public(dict(cur.fetchone()), idempotent=False)
    except Exception:
        conn.rollback()
        raise
    finally:
        db.release_conn(conn)


def claim_hosted_buyer_job(
    *, job_id: str | None = None, lease_seconds: int = 30, now: int | None = None
) -> dict[str, Any]:
    current = int(time.time()) if now is None else int(now)
    lease = max(15, min(int(lease_seconds), 300))
    init_hosted_buyer_jobs_db()
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        # Expired leases are recoverable by any worker.
        cur.execute(
            f"""UPDATE hosted_buyer_jobs SET state='queued', lease_token=NULL,
                lease_until=NULL, updated_at={p}
                WHERE state='leased' AND lease_until<{p}""",
            (current, current),
        )
        if job_id:
            cur.execute(
                f"""SELECT * FROM hosted_buyer_jobs
                    WHERE job_id={p} AND state='queued' AND next_run_at<={p}""",
                (job_id, current),
            )
        else:
            cur.execute(
                f"""SELECT * FROM hosted_buyer_jobs
                    WHERE state='queued' AND next_run_at<={p}
                    ORDER BY next_run_at, created_at LIMIT 1""",
                (current,),
            )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return {"status": "empty"}
        item = dict(row)
        token = "hbl_" + secrets.token_urlsafe(24)
        cur.execute(
            f"""UPDATE hosted_buyer_jobs SET state='leased', lease_token={p},
                lease_until={p}, attempt_count=attempt_count+1, updated_at={p}
                WHERE job_id={p} AND state='queued'""",
            (token, current + lease, current, item["job_id"]),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return {"status": "retry"}
        _record_event(
            cur, job_id=str(item["job_id"]), buyer_agent_id=str(item["buyer_agent_id"]),
            intent_decision_id=str(item["intent_decision_id"]), event_type="leased",
            state="leased", created_at=current,
        )
        conn.commit()
        item["state"] = "leased"
        item["lease_token"] = token
        item["lease_until"] = current + lease
        item["attempt_count"] = int(item.get("attempt_count") or 0) + 1
        return _public(item, include_lease=True)
    finally:
        db.release_conn(conn)


def finish_hosted_buyer_job(
    *,
    job_id: str,
    lease_token: str,
    state: str,
    action: str | None = None,
    error: str | None = None,
    next_run_at: int | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if state not in {"queued", "waiting", "completed", "stopped"}:
        raise ValueError("buyer_job_state_invalid")
    current = int(time.time()) if now is None else int(now)
    init_hosted_buyer_jobs_db()
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"""UPDATE hosted_buyer_jobs SET state={p}, lease_token=NULL,
                lease_until=NULL, last_action={p}, last_error={p},
                next_run_at={p}, updated_at={p}, completed_at={p}
                WHERE job_id={p} AND state='leased' AND lease_token={p}""",
            (
                state,
                action,
                error,
                int(next_run_at if next_run_at is not None else current),
                current,
                current if state == "completed" else None,
                job_id,
                lease_token,
            ),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return {"status": "lease_conflict", "job_id": job_id}
        cur.execute(f"SELECT buyer_agent_id, intent_decision_id FROM hosted_buyer_jobs WHERE job_id={p}", (job_id,))
        identity = cur.fetchone()
        if identity:
            _record_event(
                cur, job_id=job_id, buyer_agent_id=str(identity["buyer_agent_id"]),
                intent_decision_id=str(identity["intent_decision_id"]),
                event_type=state, state=state, action=action, error=error,
                created_at=current,
            )
        conn.commit()
        return {"status": "job_updated", "job_id": job_id, "state": state}
    finally:
        db.release_conn(conn)


def _public(row: dict[str, Any], *, idempotent: bool | None = None, include_lease: bool = False) -> dict[str, Any]:
    try:
        payload = json.loads(row.get("payload_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    result = {
        "job_id": row.get("job_id"),
        "buyer_agent_id": row.get("buyer_agent_id"),
        "intent_decision_id": row.get("intent_decision_id"),
        "state": row.get("state"),
        "next_run_at": row.get("next_run_at"),
        "attempt_count": row.get("attempt_count"),
        "max_attempts": row.get("max_attempts"),
        "last_action": row.get("last_action"),
        "last_error": row.get("last_error"),
        "payload": payload,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "completed_at": row.get("completed_at"),
    }
    if include_lease:
        result["lease_token"] = row.get("lease_token")
        result["lease_until"] = row.get("lease_until")
    if idempotent is not None:
        result["idempotent_replay"] = idempotent
    return result


def _record_event(
    cur: Any, *, job_id: str, buyer_agent_id: str, intent_decision_id: str,
    event_type: str, state: str, created_at: int, action: str | None = None,
    error: str | None = None,
) -> None:
    q = db.qmark()
    previous = cur.execute(
        f"SELECT event_hash FROM hosted_buyer_job_events WHERE job_id={q} "
        f"ORDER BY created_at DESC, event_id DESC LIMIT 1", (job_id,)
    ).fetchone()
    previous_hash = str(previous["event_hash"]) if previous else GENESIS_EVENT_HASH
    canonical = json.dumps(
        {"version": 1, "job_id": job_id, "buyer_agent_id": buyer_agent_id,
         "intent_decision_id": intent_decision_id, "event_type": event_type,
         "state": state, "action": action, "error": error,
         "created_at": int(created_at), "previous_hash": previous_hash},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    event_hash = hashlib.sha256(canonical).hexdigest()
    marks = ",".join([q] * 11)
    cur.execute(
        "INSERT INTO hosted_buyer_job_events "
        "(event_id, job_id, buyer_agent_id, intent_decision_id, event_type, state, action, error, created_at, previous_hash, event_hash) "
        f"VALUES ({marks})",
        ("hbe_" + uuid.uuid4().hex, job_id, buyer_agent_id, intent_decision_id,
         event_type, state, action, error, int(created_at), previous_hash, event_hash),
    )


def verify_hosted_buyer_job_events(job_id: str) -> dict[str, Any]:
    """Verify the append-only event chain for one hosted job."""
    init_hosted_buyer_jobs_db()
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"SELECT * FROM hosted_buyer_job_events WHERE job_id={p} "
            "ORDER BY created_at, event_id", (job_id,)
        )
        rows = [dict(row) for row in cur.fetchall()]
    finally:
        db.release_conn(conn)
    by_previous = {str(event["previous_hash"]): event for event in rows}
    previous = GENESIS_EVENT_HASH
    ordered: list[dict[str, Any]] = []
    while previous in by_previous:
        event = by_previous.pop(previous)
        ordered.append(event)
        previous = str(event["event_hash"])
    if by_previous:
        return {"status": "invalid", "job_id": job_id, "valid": False,
                "event_count": len(rows), "first_invalid_index": len(ordered),
                "head_hash": None}
    previous = GENESIS_EVENT_HASH
    for index, event in enumerate(ordered):
        canonical = json.dumps(
            {"version": 1, "job_id": str(event["job_id"]),
             "buyer_agent_id": str(event["buyer_agent_id"]),
             "intent_decision_id": str(event["intent_decision_id"]),
             "event_type": str(event["event_type"]), "state": str(event["state"]),
             "action": event.get("action"), "error": event.get("error"),
             "created_at": int(event["created_at"]), "previous_hash": previous},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        expected = hashlib.sha256(canonical).hexdigest()
        if event.get("previous_hash") != previous or event.get("event_hash") != expected:
            return {"status": "invalid", "job_id": job_id,
                    "valid": False, "event_count": len(rows),
                    "first_invalid_index": index, "head_hash": None}
        previous = expected
    return {"status": "ok", "job_id": job_id, "valid": True,
            "event_count": len(ordered), "head_hash": previous if ordered else None}
