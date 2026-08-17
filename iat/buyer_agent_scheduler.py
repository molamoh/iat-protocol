"""Persistent, bounded scheduler for autonomous buyer intents."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from iat.autonomous_buyer import AutonomousBuyerError, AutonomousBuyerRunner
from iat.wallet_adapters import WalletAdapterError


HARD_STOP_ERRORS = {
    "autonomous_policy_not_applied",
    "buyer_signature_not_required_by_transaction",
    "prepared_transaction_encoding_invalid",
    "prepared_transaction_safety_flags_invalid",
    "transaction_cluster_not_allowed",
    "transaction_fee_payer_mismatch",
    "transaction_review_missing",
    "transaction_simulation_not_succeeded",
    "wallet_address_mismatch",
    "wallet_returned_invalid_signature",
}

ACTIONABLE = {
    "advance",
    "prepare_checkout",
    "prepare_new_checkout",
    "buyer_sign_and_broadcast",
    "confirm_payment",
}

JOB_STATES = {"scheduled", "running", "waiting", "completed", "stopped"}


class BuyerAgentScheduler:
    """Persist intent jobs while executing at most one transition per cycle."""

    def __init__(
        self,
        runner: AutonomousBuyerRunner,
        database_path: str | Path,
        *,
        lease_seconds: int = 30,
        default_poll_seconds: int = 5,
    ):
        if lease_seconds < 5 or default_poll_seconds < 1:
            raise ValueError("scheduler_intervals_invalid")
        self.runner = runner
        self.database_path = str(Path(database_path).expanduser())
        self.lease_seconds = lease_seconds
        self.default_poll_seconds = default_poll_seconds
        self._lock = threading.Lock()
        Path(self.database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS buyer_agent_jobs (
                    intent_decision_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    next_run_at INTEGER NOT NULL,
                    lease_until INTEGER,
                    attempt_count INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    last_action TEXT,
                    last_error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS buyer_agent_job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent_decision_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    action TEXT,
                    error TEXT,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(intent_decision_id)
                        REFERENCES buyer_agent_jobs(intent_decision_id)
                )
                """
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_buyer_agent_job_events_intent
                   ON buyer_agent_job_events(intent_decision_id, event_id)"""
            )

    def schedule(
        self,
        intent_decision_id: str,
        *,
        now: int | None = None,
        max_attempts: int = 100,
    ) -> dict[str, Any]:
        decision_id = str(intent_decision_id).strip()
        if not decision_id or len(decision_id) > 160:
            raise ValueError("intent_decision_id_invalid")
        if not 1 <= max_attempts <= 10_000:
            raise ValueError("max_attempts_invalid")
        timestamp = int(time.time() if now is None else now)
        with self._connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO buyer_agent_jobs (
                    intent_decision_id, state, next_run_at, lease_until,
                    attempt_count, max_attempts, created_at, updated_at
                ) VALUES (?, 'scheduled', ?, NULL, 0, ?, ?, ?)
                ON CONFLICT(intent_decision_id) DO NOTHING
                """,
                (decision_id, timestamp, max_attempts, timestamp, timestamp),
            )
            if inserted.rowcount == 1:
                self._record_event(
                    connection,
                    decision_id,
                    event_type="scheduled",
                    state="scheduled",
                    created_at=timestamp,
                )
        return self.get(decision_id)

    def get(self, intent_decision_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM buyer_agent_jobs WHERE intent_decision_id = ?",
                (str(intent_decision_id),),
            ).fetchone()
        if row is None:
            raise KeyError("buyer_agent_job_not_found")
        return self._present(dict(row))

    def list_jobs(
        self,
        *,
        state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if state is not None and state not in JOB_STATES:
            raise ValueError("buyer_agent_job_state_invalid")
        if not 1 <= limit <= 100 or not 0 <= offset <= 1_000_000:
            raise ValueError("buyer_agent_job_pagination_invalid")
        where = " WHERE state = ?" if state is not None else ""
        params: tuple[Any, ...] = (state,) if state is not None else ()
        with self._connect() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM buyer_agent_jobs" + where,
                params,
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM buyer_agent_jobs"
                + where
                + " ORDER BY updated_at DESC, intent_decision_id ASC LIMIT ? OFFSET ?",
                params + (limit, offset),
            ).fetchall()
        jobs = [self._present(dict(row)) for row in rows]
        return {
            "status": "buyer_agent_jobs_listed",
            "state_filter": state,
            "jobs": jobs,
            "count": len(jobs),
            "total": int(total),
            "next_offset": offset + len(jobs) if offset + len(jobs) < int(total) else None,
        }

    def list_events(
        self,
        intent_decision_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise ValueError("buyer_agent_event_pagination_invalid")
        decision_id = str(intent_decision_id)
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM buyer_agent_jobs WHERE intent_decision_id = ?",
                (decision_id,),
            ).fetchone()
            if exists is None:
                raise KeyError("buyer_agent_job_not_found")
            total = connection.execute(
                "SELECT COUNT(*) FROM buyer_agent_job_events WHERE intent_decision_id = ?",
                (decision_id,),
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT event_id, intent_decision_id, event_type, state,
                          action, error, created_at
                   FROM buyer_agent_job_events
                   WHERE intent_decision_id = ?
                   ORDER BY event_id ASC LIMIT ? OFFSET ?""",
                (decision_id, limit, offset),
            ).fetchall()
        events = [dict(row) for row in rows]
        return {
            "status": "buyer_agent_job_events_listed",
            "intent_decision_id": decision_id,
            "events": events,
            "count": len(events),
            "total": int(total),
            "next_offset": offset + len(events) if offset + len(events) < int(total) else None,
        }

    def resume(
        self,
        intent_decision_id: str,
        *,
        additional_attempts: int = 25,
        now: int | None = None,
    ) -> dict[str, Any]:
        if not 1 <= additional_attempts <= 1_000:
            raise ValueError("additional_attempts_invalid")
        timestamp = int(time.time() if now is None else now)
        decision_id = str(intent_decision_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state, last_error, attempt_count FROM buyer_agent_jobs WHERE intent_decision_id = ?",
                (decision_id,),
            ).fetchone()
            if row is None:
                raise KeyError("buyer_agent_job_not_found")
            if row["state"] != "stopped" or row["last_error"] != "maximum_attempts_reached":
                raise ValueError("buyer_agent_job_not_recoverable")
            connection.execute(
                """UPDATE buyer_agent_jobs
                   SET state = 'scheduled', next_run_at = ?, lease_until = NULL,
                       max_attempts = ?, updated_at = ?, last_error = NULL
                   WHERE intent_decision_id = ?""",
                (
                    timestamp,
                    int(row["attempt_count"]) + additional_attempts,
                    timestamp,
                    decision_id,
                ),
            )
            self._record_event(
                connection,
                decision_id,
                event_type="resumed",
                state="scheduled",
                created_at=timestamp,
            )
        return self.get(decision_id)

    def summary(self, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT state, COUNT(*) AS count FROM buyer_agent_jobs GROUP BY state"
            ).fetchall()
            due = connection.execute(
                """SELECT COUNT(*) FROM buyer_agent_jobs
                   WHERE state IN ('scheduled', 'waiting') AND next_run_at <= ?""",
                (timestamp,),
            ).fetchone()[0]
            next_due = connection.execute(
                """SELECT MIN(next_run_at) FROM buyer_agent_jobs
                   WHERE state IN ('scheduled', 'waiting')"""
            ).fetchone()[0]
        states = {str(row["state"]): int(row["count"]) for row in rows}
        return {
            "status": "ready",
            "due_jobs": int(due),
            "next_due_at": int(next_due) if next_due is not None else None,
            "states": states,
            "total_jobs": sum(states.values()),
        }

    def run_due_once(self, *, now: int | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("scheduler_limit_invalid")
        timestamp = int(time.time() if now is None else now)
        results: list[dict[str, Any]] = []
        with self._lock:
            for _ in range(limit):
                decision_id = self._claim_one(timestamp)
                if decision_id is None:
                    break
                results.append(self._run_claimed(decision_id, timestamp))
        return results

    def _claim_one(self, now: int) -> str | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT intent_decision_id, attempt_count, max_attempts
                FROM buyer_agent_jobs
                WHERE (
                    state IN ('scheduled', 'waiting') AND next_run_at <= ?
                ) OR (
                    state = 'running' AND lease_until IS NOT NULL AND lease_until <= ?
                )
                ORDER BY next_run_at, created_at
                LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                return None
            decision_id = str(row["intent_decision_id"])
            if int(row["attempt_count"]) >= int(row["max_attempts"]):
                connection.execute(
                    """UPDATE buyer_agent_jobs
                       SET state = 'stopped', lease_until = NULL, updated_at = ?,
                           last_error = 'maximum_attempts_reached'
                       WHERE intent_decision_id = ?""",
                    (now, decision_id),
                )
                self._record_event(
                    connection,
                    decision_id,
                    event_type="stopped",
                    state="stopped",
                    error="maximum_attempts_reached",
                    created_at=now,
                )
                return decision_id
            connection.execute(
                """UPDATE buyer_agent_jobs
                   SET state = 'running', lease_until = ?, updated_at = ?,
                       attempt_count = attempt_count + 1
                   WHERE intent_decision_id = ?""",
                (now + self.lease_seconds, now, decision_id),
            )
            self._record_event(
                connection,
                decision_id,
                event_type="attempt_started",
                state="running",
                created_at=now,
            )
            return decision_id

    def _run_claimed(self, decision_id: str, now: int) -> dict[str, Any]:
        job = self.get(decision_id)
        if job["state"] == "stopped":
            return job
        try:
            lifecycle = self.runner.lifecycle(decision_id)
            action = str(lifecycle.get("next_action") or "")
            poll_seconds = self._poll_seconds(lifecycle)
            if action == "open_delivery_inbox":
                result = self.runner.open_result(decision_id)
                if result.get("status") == "buyer_result_not_ready":
                    return self._wait(decision_id, now, self._poll_seconds(result), action)
                return self._finish(decision_id, now, "completed", action=action)
            if action in ACTIONABLE:
                result = self.runner.step(decision_id)
                if result.get("status") == "buyer_signature_not_approved":
                    return self._finish(
                        decision_id,
                        now,
                        "stopped",
                        action=action,
                        error="buyer_signature_not_approved",
                    )
                return self._wait(decision_id, now, self._poll_seconds(result), action)
            if action == "wait_for_delivery":
                return self._wait(decision_id, now, poll_seconds, action)
            return self._finish(
                decision_id,
                now,
                "stopped",
                action=action or None,
                error="unsupported_or_unsafe_next_action",
            )
        except (AutonomousBuyerError, WalletAdapterError) as exc:
            code = str(getattr(exc, "code", "buyer_agent_operation_failed"))
            if code in HARD_STOP_ERRORS:
                return self._finish(decision_id, now, "stopped", error=code)
            attempts = int(self.get(decision_id)["attempt_count"])
            delay = min(60, self.default_poll_seconds * (2 ** min(attempts - 1, 4)))
            return self._wait(decision_id, now, delay, None, error=code)
        except Exception:
            return self._finish(
                decision_id,
                now,
                "stopped",
                error="unexpected_scheduler_failure",
            )

    def _poll_seconds(self, payload: dict[str, Any]) -> int:
        try:
            value = int(payload.get("poll_after_seconds") or self.default_poll_seconds)
        except (TypeError, ValueError):
            value = self.default_poll_seconds
        return max(1, min(value, 300))

    def _wait(
        self,
        decision_id: str,
        now: int,
        delay: int,
        action: str | None,
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        job = self.get(decision_id)
        if int(job["attempt_count"]) >= int(job["max_attempts"]):
            return self._finish(
                decision_id,
                now,
                "stopped",
                action=action,
                error="maximum_attempts_reached",
            )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_jobs
                   SET state = 'waiting', next_run_at = ?, lease_until = NULL,
                       updated_at = ?, last_action = ?, last_error = ?
                   WHERE intent_decision_id = ?""",
                (now + delay, now, action, error, decision_id),
            )
            self._record_event(
                connection,
                decision_id,
                event_type="retry_scheduled" if error else "waiting",
                state="waiting",
                action=action,
                error=error,
                created_at=now,
            )
        return self.get(decision_id)

    def _finish(
        self,
        decision_id: str,
        now: int,
        state: str,
        *,
        action: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_jobs
                   SET state = ?, lease_until = NULL, updated_at = ?,
                       last_action = ?, last_error = ?
                   WHERE intent_decision_id = ?""",
                (state, now, action, error, decision_id),
            )
            self._record_event(
                connection,
                decision_id,
                event_type="completed" if state == "completed" else "stopped",
                state=state,
                action=action,
                error=error,
                created_at=now,
            )
        return self.get(decision_id)

    @staticmethod
    def _record_event(
        connection: sqlite3.Connection,
        intent_decision_id: str,
        *,
        event_type: str,
        state: str,
        created_at: int,
        action: str | None = None,
        error: str | None = None,
    ) -> None:
        connection.execute(
            """INSERT INTO buyer_agent_job_events (
                   intent_decision_id, event_type, state, action, error, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (intent_decision_id, event_type, state, action, error, created_at),
        )

    @staticmethod
    def _present(job: dict[str, Any]) -> dict[str, Any]:
        state = str(job.get("state") or "")
        error = str(job.get("last_error") or "")
        if state == "completed":
            category, action = "completed", "open_or_use_result"
        elif state in {"scheduled", "running", "waiting"}:
            category, action = "in_progress", "wait_for_scheduler"
        elif error == "maximum_attempts_reached":
            category, action = "retry_budget_exhausted", "review_then_extend_attempt_budget"
        elif error == "buyer_signature_not_approved":
            category, action = "local_policy_denied", "review_local_purchase_policy"
        elif error in HARD_STOP_ERRORS:
            category, action = "security_boundary", "inspect_security_evidence"
        elif error == "unsupported_or_unsafe_next_action":
            category, action = "protocol_state", "inspect_intent_lifecycle"
        else:
            category, action = "local_failure", "inspect_local_worker_logs"
        return {
            **job,
            "recoverable": state == "stopped" and error == "maximum_attempts_reached",
            "reason_category": category,
            "recommended_action": action,
        }
