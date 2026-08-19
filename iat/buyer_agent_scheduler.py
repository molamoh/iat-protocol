"""Persistent, bounded scheduler for autonomous buyer intents."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey
from solders.signature import Signature

from iat.attested_wallet_signer import build_evidence_message
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
GENESIS_EVENT_HASH = "0" * 64


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
                    last_error TEXT,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    event_head_hash TEXT NOT NULL DEFAULT
                        '0000000000000000000000000000000000000000000000000000000000000000'
                )
                """
            )
            job_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(buyer_agent_jobs)")
            }
            if "event_count" not in job_columns:
                connection.execute(
                    "ALTER TABLE buyer_agent_jobs ADD COLUMN event_count INTEGER NOT NULL DEFAULT 0"
                )
            if "event_head_hash" not in job_columns:
                connection.execute(
                    """ALTER TABLE buyer_agent_jobs ADD COLUMN event_head_hash TEXT NOT NULL
                       DEFAULT '0000000000000000000000000000000000000000000000000000000000000000'"""
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
                    previous_hash TEXT,
                    event_hash TEXT,
                    FOREIGN KEY(intent_decision_id)
                        REFERENCES buyer_agent_jobs(intent_decision_id)
                )
                """
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_buyer_agent_job_events_intent
                   ON buyer_agent_job_events(intent_decision_id, event_id)"""
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(buyer_agent_job_events)")
            }
            if "previous_hash" not in columns:
                connection.execute(
                    "ALTER TABLE buyer_agent_job_events ADD COLUMN previous_hash TEXT"
                )
            if "event_hash" not in columns:
                connection.execute(
                    "ALTER TABLE buyer_agent_job_events ADD COLUMN event_hash TEXT"
                )
            event_count, hashed_count = connection.execute(
                """SELECT COUNT(*), COUNT(event_hash)
                   FROM buyer_agent_job_events"""
            ).fetchone()
            if int(event_count) and not int(hashed_count):
                self._backfill_event_hashes(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS buyer_agent_job_anchors (
                    anchor_id TEXT PRIMARY KEY,
                    intent_decision_id TEXT NOT NULL UNIQUE,
                    evidence_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 10,
                    next_run_at INTEGER NOT NULL,
                    lease_until INTEGER,
                    observed_at INTEGER,
                    wallet_address TEXT,
                    signature TEXT,
                    publication_attempt_count INTEGER NOT NULL DEFAULT 0,
                    publication_max_attempts INTEGER NOT NULL DEFAULT 10,
                    publication_next_run_at INTEGER,
                    publication_lease_until INTEGER,
                    publication_error TEXT,
                    receipt_id TEXT,
                    receipt_sha256 TEXT,
                    published_at INTEGER,
                    validation_attempt_count INTEGER NOT NULL DEFAULT 0,
                    validation_max_attempts INTEGER NOT NULL DEFAULT 10,
                    validation_next_run_at INTEGER,
                    validation_lease_until INTEGER,
                    validation_error TEXT,
                    validation_id TEXT,
                    validation_sha256 TEXT,
                    validation_decision TEXT,
                    validation_reason TEXT,
                    validated_at INTEGER,
                    quality_attempt_count INTEGER NOT NULL DEFAULT 0,
                    quality_max_attempts INTEGER NOT NULL DEFAULT 10,
                    quality_next_run_at INTEGER,
                    quality_lease_until INTEGER,
                    quality_error TEXT,
                    quality_validation_id TEXT,
                    quality_validation_sha256 TEXT,
                    quality_decision TEXT,
                    quality_criteria_sha256 TEXT,
                    quality_passed_count INTEGER,
                    quality_failed_count INTEGER,
                    quality_validated_at INTEGER,
                    eligibility_attempt_count INTEGER NOT NULL DEFAULT 0,
                    eligibility_max_attempts INTEGER NOT NULL DEFAULT 10,
                    eligibility_next_run_at INTEGER,
                    eligibility_lease_until INTEGER,
                    eligibility_error TEXT,
                    eligibility_id TEXT,
                    eligibility_sha256 TEXT,
                    eligibility_decision TEXT,
                    eligibility_reason TEXT,
                    settlement_id TEXT,
                    eligibility_evaluated_at INTEGER,
                    plan_attempt_count INTEGER NOT NULL DEFAULT 0,
                    plan_max_attempts INTEGER NOT NULL DEFAULT 10,
                    plan_next_run_at INTEGER,
                    plan_lease_until INTEGER,
                    plan_error TEXT,
                    plan_id TEXT,
                    plan_sha256 TEXT,
                    plan_decision TEXT,
                    planned_at INTEGER,
                    authorization_attempt_count INTEGER NOT NULL DEFAULT 0,
                    authorization_max_attempts INTEGER NOT NULL DEFAULT 10,
                    authorization_next_run_at INTEGER,
                    authorization_lease_until INTEGER,
                    authorization_error TEXT,
                    authorization_id TEXT,
                    authorization_sha256 TEXT,
                    authorization_mode TEXT,
                    authorization_reason TEXT,
                    authorized_at INTEGER,
                    simulation_attempt_count INTEGER NOT NULL DEFAULT 0,
                    simulation_max_attempts INTEGER NOT NULL DEFAULT 10,
                    simulation_next_run_at INTEGER,
                    simulation_lease_until INTEGER,
                    simulation_error TEXT,
                    simulation_id TEXT,
                    simulation_sha256 TEXT,
                    simulation_cluster TEXT,
                    simulation_genesis_hash TEXT,
                    simulation_mint TEXT,
                    simulation_transaction_sha256 TEXT,
                    simulation_units_consumed INTEGER,
                    simulation_context_slot INTEGER,
                    simulated_at INTEGER,
                    permit_attempt_count INTEGER NOT NULL DEFAULT 0,
                    permit_max_attempts INTEGER NOT NULL DEFAULT 10,
                    permit_next_run_at INTEGER,
                    permit_lease_until INTEGER,
                    permit_error TEXT,
                    permit_id TEXT,
                    permit_sha256 TEXT,
                    permit_state TEXT,
                    permit_expires_at INTEGER,
                    permit_issued_at INTEGER,
                    last_error TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(intent_decision_id)
                        REFERENCES buyer_agent_jobs(intent_decision_id)
                )
                """
            )
            anchor_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(buyer_agent_job_anchors)")
            }
            anchor_migrations = {
                "publication_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "publication_max_attempts": "INTEGER NOT NULL DEFAULT 10",
                "publication_next_run_at": "INTEGER",
                "publication_lease_until": "INTEGER",
                "publication_error": "TEXT",
                "receipt_id": "TEXT",
                "receipt_sha256": "TEXT",
                "published_at": "INTEGER",
                "validation_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "validation_max_attempts": "INTEGER NOT NULL DEFAULT 10",
                "validation_next_run_at": "INTEGER",
                "validation_lease_until": "INTEGER",
                "validation_error": "TEXT",
                "validation_id": "TEXT",
                "validation_sha256": "TEXT",
                "validation_decision": "TEXT",
                "validation_reason": "TEXT",
                "validated_at": "INTEGER",
                "quality_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "quality_max_attempts": "INTEGER NOT NULL DEFAULT 10",
                "quality_next_run_at": "INTEGER",
                "quality_lease_until": "INTEGER",
                "quality_error": "TEXT",
                "quality_validation_id": "TEXT",
                "quality_validation_sha256": "TEXT",
                "quality_decision": "TEXT",
                "quality_criteria_sha256": "TEXT",
                "quality_passed_count": "INTEGER",
                "quality_failed_count": "INTEGER",
                "quality_validated_at": "INTEGER",
                "eligibility_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "eligibility_max_attempts": "INTEGER NOT NULL DEFAULT 10",
                "eligibility_next_run_at": "INTEGER",
                "eligibility_lease_until": "INTEGER",
                "eligibility_error": "TEXT",
                "eligibility_id": "TEXT",
                "eligibility_sha256": "TEXT",
                "eligibility_decision": "TEXT",
                "eligibility_reason": "TEXT",
                "settlement_id": "TEXT",
                "eligibility_evaluated_at": "INTEGER",
                "plan_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "plan_max_attempts": "INTEGER NOT NULL DEFAULT 10",
                "plan_next_run_at": "INTEGER",
                "plan_lease_until": "INTEGER",
                "plan_error": "TEXT",
                "plan_id": "TEXT",
                "plan_sha256": "TEXT",
                "plan_decision": "TEXT",
                "planned_at": "INTEGER",
                "authorization_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "authorization_max_attempts": "INTEGER NOT NULL DEFAULT 10",
                "authorization_next_run_at": "INTEGER",
                "authorization_lease_until": "INTEGER",
                "authorization_error": "TEXT",
                "authorization_id": "TEXT",
                "authorization_sha256": "TEXT",
                "authorization_mode": "TEXT",
                "authorization_reason": "TEXT",
                "authorized_at": "INTEGER",
                "simulation_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "simulation_max_attempts": "INTEGER NOT NULL DEFAULT 10",
                "simulation_next_run_at": "INTEGER",
                "simulation_lease_until": "INTEGER",
                "simulation_error": "TEXT",
                "simulation_id": "TEXT",
                "simulation_sha256": "TEXT",
                "simulation_cluster": "TEXT",
                "simulation_genesis_hash": "TEXT",
                "simulation_mint": "TEXT",
                "simulation_transaction_sha256": "TEXT",
                "simulation_units_consumed": "INTEGER",
                "simulation_context_slot": "INTEGER",
                "simulated_at": "INTEGER",
                "permit_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "permit_max_attempts": "INTEGER NOT NULL DEFAULT 10",
                "permit_next_run_at": "INTEGER",
                "permit_lease_until": "INTEGER",
                "permit_error": "TEXT",
                "permit_id": "TEXT",
                "permit_sha256": "TEXT",
                "permit_state": "TEXT",
                "permit_expires_at": "INTEGER",
                "permit_issued_at": "INTEGER",
            }
            for column, definition in anchor_migrations.items():
                if column not in anchor_columns:
                    connection.execute(
                        f"ALTER TABLE buyer_agent_job_anchors ADD COLUMN {column} {definition}"
                    )
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET publication_next_run_at = updated_at
                   WHERE state = 'attested' AND publication_next_run_at IS NULL"""
            )
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET validation_next_run_at = updated_at
                   WHERE state = 'published' AND validation_next_run_at IS NULL"""
            )
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET quality_next_run_at = updated_at
                   WHERE state = 'delivery_verified' AND quality_next_run_at IS NULL"""
            )
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET eligibility_next_run_at = updated_at
                   WHERE state IN ('quality_accepted', 'quality_rejected')
                     AND eligibility_next_run_at IS NULL"""
            )
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET plan_next_run_at = updated_at
                   WHERE state = 'release_eligible' AND plan_next_run_at IS NULL"""
            )
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET authorization_next_run_at = updated_at
                   WHERE state = 'settlement_planned'
                     AND authorization_next_run_at IS NULL"""
            )
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET simulation_next_run_at = updated_at
                   WHERE state = 'settlement_authorized'
                     AND simulation_next_run_at IS NULL"""
            )
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET permit_next_run_at = updated_at
                   WHERE state = 'settlement_simulated'
                     AND permit_next_run_at IS NULL"""
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_buyer_agent_job_anchors_due
                   ON buyer_agent_job_anchors(state, next_run_at)"""
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
                          action, error, created_at, previous_hash, event_hash
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

    def verify_event_chain(self, intent_decision_id: str) -> dict[str, Any]:
        decision_id = str(intent_decision_id)
        history = self.list_events(decision_id, limit=200, offset=0)
        with self._connect() as connection:
            job = connection.execute(
                """SELECT event_count, event_head_hash FROM buyer_agent_jobs
                   WHERE intent_decision_id = ?""",
                (decision_id,),
            ).fetchone()
        if history["total"] > 200:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT event_id, intent_decision_id, event_type, state,
                              action, error, created_at, previous_hash, event_hash
                       FROM buyer_agent_job_events
                       WHERE intent_decision_id = ? ORDER BY event_id ASC""",
                    (decision_id,),
                ).fetchall()
            events = [dict(row) for row in rows]
        else:
            events = history["events"]
        previous_hash = GENESIS_EVENT_HASH
        for event in events:
            expected = self._event_hash(event, previous_hash)
            if not hmac.compare_digest(str(event.get("previous_hash") or ""), previous_hash):
                return self._verification_result(decision_id, events, event["event_id"])
            if not hmac.compare_digest(str(event.get("event_hash") or ""), expected):
                return self._verification_result(decision_id, events, event["event_id"])
            previous_hash = expected
        if int(job["event_count"]) != len(events):
            return self._verification_result(decision_id, events, None)
        if not hmac.compare_digest(str(job["event_head_hash"]), previous_hash):
            return self._verification_result(decision_id, events, None)
        return {
            "status": "buyer_agent_event_chain_verified",
            "intent_decision_id": decision_id,
            "valid": True,
            "event_count": len(events),
            "head_hash": previous_hash,
            "first_invalid_event_id": None,
        }

    def get_anchor(self, intent_decision_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM buyer_agent_job_anchors
                   WHERE intent_decision_id = ?""",
                (str(intent_decision_id),),
            ).fetchone()
        if row is None:
            raise KeyError("buyer_agent_anchor_not_found")
        return dict(row)

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
            anchor_rows = connection.execute(
                """SELECT state, COUNT(*) AS count
                   FROM buyer_agent_job_anchors GROUP BY state"""
            ).fetchall()
        states = {str(row["state"]): int(row["count"]) for row in rows}
        anchor_states = {
            str(row["state"]): int(row["count"]) for row in anchor_rows
        }
        return {
            "status": "ready",
            "due_jobs": int(due),
            "next_due_at": int(next_due) if next_due is not None else None,
            "states": states,
            "anchor_states": anchor_states,
            "total_jobs": sum(states.values()),
        }

    def run_due_once(self, *, now: int | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("scheduler_limit_invalid")
        timestamp = int(time.time() if now is None else now)
        results: list[dict[str, Any]] = []
        with self._lock:
            permit_id = self._claim_settlement_phase(
                timestamp,
                ready_state="settlement_simulated",
                working_state="settlement_permitting",
                failed_state="settlement_permit_failed",
                prefix="permit",
            )
            if permit_id is not None:
                results.append(self._run_settlement_permit(permit_id, timestamp))
            elif (simulation_id := self._claim_settlement_phase(
                timestamp,
                ready_state="settlement_authorized",
                working_state="settlement_simulating",
                failed_state="settlement_simulation_failed",
                prefix="simulation",
            )) is not None:
                results.append(self._run_settlement_simulation(simulation_id, timestamp))
            elif (authorization_id := self._claim_settlement_phase(
                timestamp,
                ready_state="settlement_planned",
                working_state="settlement_authorizing",
                failed_state="settlement_authorization_failed",
                prefix="authorization",
            )) is not None:
                results.append(
                    self._run_settlement_authorization(authorization_id, timestamp)
                )
            elif (plan_id := self._claim_settlement_phase(
                timestamp,
                ready_state="release_eligible",
                working_state="settlement_planning",
                failed_state="settlement_planning_failed",
                prefix="plan",
            )) is not None:
                results.append(self._run_settlement_plan(plan_id, timestamp))
            elif (eligibility_id := self._claim_settlement_eligibility(timestamp)) is not None:
                results.append(self._run_settlement_eligibility(eligibility_id, timestamp))
            elif (quality_id := self._claim_quality_validation(timestamp)) is not None:
                results.append(self._run_quality_validation(quality_id, timestamp))
            elif (validation_id := self._claim_validation(timestamp)) is not None:
                results.append(self._run_validation(validation_id, timestamp))
            elif (publication_id := self._claim_publication(timestamp)) is not None:
                results.append(self._run_publication(publication_id, timestamp))
            elif (anchor_id := self._claim_anchor(timestamp)) is not None:
                results.append(self._run_anchor(anchor_id, timestamp))
            for _ in range(limit - len(results)):
                decision_id = self._claim_one(timestamp)
                if decision_id is None:
                    break
                results.append(self._run_claimed(decision_id, timestamp))
        return results

    def _claim_settlement_phase(
        self,
        now: int,
        *,
        ready_state: str,
        working_state: str,
        failed_state: str,
        prefix: str,
    ) -> str | None:
        if prefix not in {"plan", "authorization", "simulation", "permit"}:
            raise ValueError("settlement_phase_invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""SELECT anchor_id, {prefix}_attempt_count, {prefix}_max_attempts
                    FROM buyer_agent_job_anchors
                    WHERE (state = ? AND {prefix}_next_run_at <= ?)
                       OR (state = ? AND {prefix}_lease_until IS NOT NULL
                           AND {prefix}_lease_until <= ?)
                    ORDER BY {prefix}_next_run_at, created_at LIMIT 1""",
                (ready_state, now, working_state, now),
            ).fetchone()
            if row is None:
                return None
            anchor_id = str(row["anchor_id"])
            if int(row[f"{prefix}_attempt_count"]) >= int(
                row[f"{prefix}_max_attempts"]
            ):
                connection.execute(
                    f"""UPDATE buyer_agent_job_anchors
                        SET state = ?, {prefix}_lease_until = NULL,
                            {prefix}_error = ?, updated_at = ?
                        WHERE anchor_id = ?""",
                    (
                        failed_state,
                        f"maximum_{prefix}_attempts_reached",
                        now,
                        anchor_id,
                    ),
                )
                return anchor_id
            connection.execute(
                f"""UPDATE buyer_agent_job_anchors
                    SET state = ?, {prefix}_lease_until = ?,
                        {prefix}_attempt_count = {prefix}_attempt_count + 1,
                        updated_at = ? WHERE anchor_id = ?""",
                (working_state, now + self.lease_seconds, now, anchor_id),
            )
            return anchor_id

    def _retry_settlement_phase(
        self,
        anchor: dict[str, Any],
        now: int,
        *,
        prefix: str,
        ready_state: str,
        failed_state: str,
        error: str,
    ) -> dict[str, Any]:
        attempts = int(anchor[f"{prefix}_attempt_count"])
        exhausted = attempts >= int(anchor[f"{prefix}_max_attempts"])
        delay = min(300, self.default_poll_seconds * (2 ** min(attempts - 1, 5)))
        state = failed_state if exhausted else ready_state
        with self._connect() as connection:
            connection.execute(
                f"""UPDATE buyer_agent_job_anchors
                    SET state = ?, {prefix}_next_run_at = ?,
                        {prefix}_lease_until = NULL, {prefix}_error = ?,
                        updated_at = ? WHERE anchor_id = ?""",
                (
                    state,
                    now if exhausted else now + delay,
                    error,
                    now,
                    anchor["anchor_id"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor["anchor_id"],),
            ).fetchone()
        return {"work_type": f"settlement_{prefix}", **dict(row)}

    def _run_settlement_plan(self, anchor_id: str, now: int) -> dict[str, Any]:
        anchor = self._anchor_row(anchor_id)
        if anchor["state"] == "settlement_planning_failed":
            return {"work_type": "settlement_plan", **anchor}
        try:
            plan = self.runner.plan_settlement_execution(anchor["eligibility_id"])
            bindings = (
                str(plan.get("eligibility_id") or "") == str(anchor["eligibility_id"])
                and plan.get("effect") == "planning_only"
                and plan.get("execution_enabled") is False
                and plan.get("transaction_built") is False
                and plan.get("transaction_signed") is False
                and plan.get("transaction_broadcast") is False
                and plan.get("funds_moved") is False
                and str(plan.get("plan_id") or "").startswith("psp_")
                and len(str(plan.get("plan_sha256") or "")) == 64
            )
            if not bindings:
                raise AutonomousBuyerError("protocol_settlement_plan_mismatch")
        except AutonomousBuyerError as exc:
            return self._retry_settlement_phase(
                anchor, now, prefix="plan", ready_state="release_eligible",
                failed_state="settlement_planning_failed", error=exc.code,
            )
        except Exception:
            return self._retry_settlement_phase(
                anchor, now, prefix="plan", ready_state="release_eligible",
                failed_state="settlement_planning_failed",
                error="unexpected_settlement_plan_failure",
            )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'settlement_planned', plan_lease_until = NULL,
                       plan_error = NULL, plan_id = ?, plan_sha256 = ?,
                       plan_decision = ?, planned_at = ?,
                       authorization_next_run_at = ?, updated_at = ?
                   WHERE anchor_id = ?""",
                (
                    plan["plan_id"], plan["plan_sha256"], plan.get("decision"),
                    int(plan.get("evaluated_at") or now), now, now, anchor_id,
                ),
            )
        return {"work_type": "settlement_plan", **self.get_anchor(
            str(anchor["intent_decision_id"])
        )}

    def _run_settlement_authorization(self, anchor_id: str, now: int) -> dict[str, Any]:
        anchor = self._anchor_row(anchor_id)
        if anchor["state"] == "settlement_authorization_failed":
            return {"work_type": "settlement_authorization", **anchor}
        try:
            authorization = self.runner.authorize_settlement_plan(anchor["plan_id"])
            bindings = (
                str(authorization.get("plan_id") or "") == str(anchor["plan_id"])
                and authorization.get("release_authorized") is True
                and authorization.get("authorized_by") == "foundation"
                and authorization.get("effect") == "authorization_only"
                and authorization.get("execution_enabled") is False
                and authorization.get("transaction_built") is False
                and authorization.get("transaction_signed") is False
                and authorization.get("transaction_broadcast") is False
                and authorization.get("funds_moved") is False
                and str(authorization.get("authorization_id") or "").startswith("psa_")
                and len(str(authorization.get("authorization_sha256") or "")) == 64
            )
            if not bindings:
                raise AutonomousBuyerError("protocol_settlement_authorization_mismatch")
        except AutonomousBuyerError as exc:
            return self._retry_settlement_phase(
                anchor, now, prefix="authorization", ready_state="settlement_planned",
                failed_state="settlement_authorization_failed", error=exc.code,
            )
        except Exception:
            return self._retry_settlement_phase(
                anchor, now, prefix="authorization", ready_state="settlement_planned",
                failed_state="settlement_authorization_failed",
                error="unexpected_settlement_authorization_failure",
            )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'settlement_authorized',
                       authorization_lease_until = NULL, authorization_error = NULL,
                       authorization_id = ?, authorization_sha256 = ?,
                       authorization_mode = ?, authorization_reason = ?,
                       authorized_at = ?, simulation_next_run_at = ?, updated_at = ?
                   WHERE anchor_id = ?""",
                (
                    authorization["authorization_id"],
                    authorization["authorization_sha256"],
                    authorization.get("authorization_mode"),
                    authorization.get("authorization_reason"),
                    int(authorization.get("authorized_at") or now), now, now, anchor_id,
                ),
            )
        return {"work_type": "settlement_authorization", **self.get_anchor(
            str(anchor["intent_decision_id"])
        )}

    def _run_settlement_simulation(self, anchor_id: str, now: int) -> dict[str, Any]:
        anchor = self._anchor_row(anchor_id)
        if anchor["state"] == "settlement_simulation_failed":
            return {"work_type": "settlement_simulation", **anchor}
        try:
            simulation = self.runner.simulate_settlement(anchor["authorization_id"])
            bindings = (
                str(simulation.get("authorization_id") or "")
                == str(anchor["authorization_id"])
                and simulation.get("effect") == "simulation_only"
                and simulation.get("execution_enabled") is False
                and simulation.get("unsigned_transaction_built") is True
                and simulation.get("serialized_transaction_disclosed") is False
                and simulation.get("transaction_signed") is False
                and simulation.get("transaction_broadcast") is False
                and simulation.get("funds_moved") is False
                and simulation.get("cluster") in {"solana-devnet", "solana-localnet"}
                and str(simulation.get("simulation_id") or "").startswith("pss_")
                and len(str(simulation.get("simulation_sha256") or "")) == 64
                and len(str(simulation.get("unsigned_transaction_sha256") or "")) == 64
            )
            if not bindings:
                raise AutonomousBuyerError("protocol_settlement_simulation_mismatch")
        except AutonomousBuyerError as exc:
            return self._retry_settlement_phase(
                anchor, now, prefix="simulation", ready_state="settlement_authorized",
                failed_state="settlement_simulation_failed", error=exc.code,
            )
        except Exception:
            return self._retry_settlement_phase(
                anchor, now, prefix="simulation", ready_state="settlement_authorized",
                failed_state="settlement_simulation_failed",
                error="unexpected_settlement_simulation_failure",
            )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'settlement_simulated', simulation_lease_until = NULL,
                       simulation_error = NULL, simulation_id = ?,
                       simulation_sha256 = ?, simulation_cluster = ?,
                       simulation_genesis_hash = ?, simulation_mint = ?,
                       simulation_transaction_sha256 = ?,
                       simulation_units_consumed = ?, simulation_context_slot = ?,
                       simulated_at = ?, permit_next_run_at = ?, updated_at = ?
                   WHERE anchor_id = ?""",
                (
                    simulation["simulation_id"], simulation["simulation_sha256"],
                    simulation["cluster"], simulation.get("genesis_hash"),
                    simulation.get("mint"), simulation["unsigned_transaction_sha256"],
                    simulation.get("units_consumed"), simulation.get("context_slot"),
                    int(simulation.get("simulated_at") or now), now, now, anchor_id,
                ),
            )
        return {"work_type": "settlement_simulation", **self.get_anchor(
            str(anchor["intent_decision_id"])
        )}

    def _run_settlement_permit(self, anchor_id: str, now: int) -> dict[str, Any]:
        anchor = self._anchor_row(anchor_id)
        if anchor["state"] == "settlement_permit_failed":
            return {"work_type": "settlement_permit", **anchor}
        try:
            permit = self.runner.issue_settlement_execution_permit(
                anchor["simulation_id"]
            )
            bindings = (
                str(permit.get("simulation_id") or "") == str(anchor["simulation_id"])
                and permit.get("state") == "issued"
                and permit.get("effect") == "execution_authorization_only"
                and permit.get("one_time") is True
                and permit.get("claim_required") is True
                and permit.get("currently_valid") is True
                and permit.get("public_claim_available") is False
                and permit.get("transaction_built") is False
                and permit.get("transaction_signed") is False
                and permit.get("transaction_broadcast") is False
                and permit.get("funds_moved") is False
                and str(permit.get("permit_id") or "").startswith("pep_")
                and len(str(permit.get("permit_sha256") or "")) == 64
            )
            if not bindings:
                raise AutonomousBuyerError("protocol_settlement_execution_permit_mismatch")
        except AutonomousBuyerError as exc:
            return self._retry_settlement_phase(
                anchor, now, prefix="permit", ready_state="settlement_simulated",
                failed_state="settlement_permit_failed", error=exc.code,
            )
        except Exception:
            return self._retry_settlement_phase(
                anchor, now, prefix="permit", ready_state="settlement_simulated",
                failed_state="settlement_permit_failed",
                error="unexpected_settlement_permit_failure",
            )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'settlement_execution_permitted',
                       permit_lease_until = NULL, permit_error = NULL,
                       permit_id = ?, permit_sha256 = ?, permit_state = ?,
                       permit_expires_at = ?, permit_issued_at = ?, updated_at = ?
                   WHERE anchor_id = ?""",
                (
                    permit["permit_id"], permit["permit_sha256"], permit["state"],
                    int(permit["expires_at"]), int(permit["issued_at"]), now, anchor_id,
                ),
            )
        return {"work_type": "settlement_permit", **self.get_anchor(
            str(anchor["intent_decision_id"])
        )}

    def _anchor_row(self, anchor_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        return dict(row)

    def _claim_settlement_eligibility(self, now: int) -> str | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT anchor_id, eligibility_attempt_count,
                          eligibility_max_attempts
                   FROM buyer_agent_job_anchors
                   WHERE (state IN ('quality_accepted', 'quality_rejected')
                          AND eligibility_next_run_at <= ?)
                      OR (state = 'eligibility_evaluating'
                          AND eligibility_lease_until IS NOT NULL
                          AND eligibility_lease_until <= ?)
                   ORDER BY eligibility_next_run_at, created_at LIMIT 1""",
                (now, now),
            ).fetchone()
            if row is None:
                return None
            anchor_id = str(row["anchor_id"])
            if int(row["eligibility_attempt_count"]) >= int(
                row["eligibility_max_attempts"]
            ):
                connection.execute(
                    """UPDATE buyer_agent_job_anchors
                       SET state = 'settlement_eligibility_failed',
                           eligibility_lease_until = NULL,
                           eligibility_error = 'maximum_eligibility_attempts_reached',
                           updated_at = ? WHERE anchor_id = ?""",
                    (now, anchor_id),
                )
                return anchor_id
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'eligibility_evaluating', eligibility_lease_until = ?,
                       eligibility_attempt_count = eligibility_attempt_count + 1,
                       updated_at = ? WHERE anchor_id = ?""",
                (now + self.lease_seconds, now, anchor_id),
            )
            return anchor_id

    def _run_settlement_eligibility(self, anchor_id: str, now: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        anchor = dict(row)
        if anchor["state"] == "settlement_eligibility_failed":
            return {"work_type": "settlement_eligibility", **anchor}
        try:
            eligibility = self.runner.evaluate_settlement_eligibility(
                anchor["quality_validation_id"]
            )
            decision = str(eligibility.get("decision") or "")
            bindings = (
                str(eligibility.get("quality_validation_id") or "")
                == str(anchor["quality_validation_id"])
                and decision
                in {"eligible_for_governed_release", "eligible_for_compensation_review"}
                and eligibility.get("effect") == "eligibility_only"
                and eligibility.get("funds_moved") is False
                and eligibility.get("transaction_signed") is False
                and eligibility.get("transaction_broadcast") is False
                and str(eligibility.get("eligibility_id") or "").startswith("pse_")
                and len(str(eligibility.get("eligibility_sha256") or "")) == 64
            )
            if not bindings:
                raise AutonomousBuyerError("protocol_settlement_eligibility_mismatch")
        except AutonomousBuyerError as exc:
            attempts = int(anchor["eligibility_attempt_count"])
            if attempts >= int(anchor["eligibility_max_attempts"]):
                return self._finish_settlement_eligibility(
                    anchor_id, now, state="settlement_eligibility_failed", error=exc.code
                )
            delay = min(300, self.default_poll_seconds * (2 ** min(attempts - 1, 5)))
            prior_state = (
                "quality_accepted"
                if anchor["quality_decision"] == "accepted_by_explicit_criteria"
                else "quality_rejected"
            )
            return self._finish_settlement_eligibility(
                anchor_id,
                now,
                state=prior_state,
                error=exc.code,
                next_run_at=now + delay,
            )
        except Exception:
            return self._finish_settlement_eligibility(
                anchor_id,
                now,
                state="settlement_eligibility_failed",
                error="unexpected_eligibility_failure",
            )
        final_state = (
            "release_eligible"
            if decision == "eligible_for_governed_release"
            else "compensation_review_eligible"
        )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = ?, eligibility_lease_until = NULL,
                       eligibility_error = NULL, eligibility_id = ?,
                       eligibility_sha256 = ?, eligibility_decision = ?,
                       eligibility_reason = ?, settlement_id = ?,
                       eligibility_evaluated_at = ?, updated_at = ?
                   WHERE anchor_id = ?""",
                (
                    final_state,
                    str(eligibility["eligibility_id"]),
                    str(eligibility["eligibility_sha256"]),
                    decision,
                    str(eligibility.get("reason") or ""),
                    eligibility.get("settlement_id"),
                    int(eligibility.get("evaluated_at") or now),
                    now,
                    anchor_id,
                ),
            )
            if final_state == "release_eligible":
                connection.execute(
                    """UPDATE buyer_agent_job_anchors SET plan_next_run_at = ?
                       WHERE anchor_id = ?""",
                    (now, anchor_id),
                )
        return {"work_type": "settlement_eligibility", **self.get_anchor(
            str(anchor["intent_decision_id"])
        )}

    def _finish_settlement_eligibility(
        self,
        anchor_id: str,
        now: int,
        *,
        state: str,
        error: str,
        next_run_at: int | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = ?, eligibility_next_run_at = ?,
                       eligibility_lease_until = NULL, eligibility_error = ?,
                       updated_at = ? WHERE anchor_id = ?""",
                (state, next_run_at or now, error, now, anchor_id),
            )
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        return {"work_type": "settlement_eligibility", **dict(row)}

    def _claim_quality_validation(self, now: int) -> str | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT anchor_id, quality_attempt_count, quality_max_attempts
                   FROM buyer_agent_job_anchors
                   WHERE (state = 'delivery_verified' AND quality_next_run_at <= ?)
                      OR (state = 'quality_validating' AND quality_lease_until IS NOT NULL
                          AND quality_lease_until <= ?)
                   ORDER BY quality_next_run_at, created_at LIMIT 1""",
                (now, now),
            ).fetchone()
            if row is None:
                return None
            anchor_id = str(row["anchor_id"])
            if int(row["quality_attempt_count"]) >= int(row["quality_max_attempts"]):
                connection.execute(
                    """UPDATE buyer_agent_job_anchors
                       SET state = 'quality_validation_failed', quality_lease_until = NULL,
                           quality_error = 'maximum_quality_attempts_reached', updated_at = ?
                       WHERE anchor_id = ?""",
                    (now, anchor_id),
                )
                return anchor_id
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'quality_validating', quality_lease_until = ?,
                       quality_attempt_count = quality_attempt_count + 1, updated_at = ?
                   WHERE anchor_id = ?""",
                (now + self.lease_seconds, now, anchor_id),
            )
            return anchor_id

    def _run_quality_validation(self, anchor_id: str, now: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        anchor = dict(row)
        if anchor["state"] == "quality_validation_failed":
            return {"work_type": "quality_validation", **anchor}
        try:
            quality = self.runner.validate_delivery_quality(anchor["validation_id"])
            decision = str(quality.get("decision") or "")
            bindings = (
                str(quality.get("delivery_validation_id") or "")
                == str(anchor["validation_id"])
                and decision
                in {"accepted_by_explicit_criteria", "rejected_by_explicit_criteria"}
                and quality.get("effect") == "evidence_only"
                and quality.get("content_disclosed") is False
                and str(quality.get("quality_validation_id") or "").startswith("pqv_")
                and len(str(quality.get("quality_validation_sha256") or "")) == 64
            )
            if not bindings:
                raise AutonomousBuyerError("protocol_quality_validation_mismatch")
        except AutonomousBuyerError as exc:
            response = (
                exc.details.get("response", {})
                if isinstance(exc.details, dict)
                else {}
            )
            if response.get("detail") == "acceptance_criteria_not_declared":
                return self._finish_quality_validation(
                    anchor_id,
                    now,
                    state="quality_not_configured",
                    error=None,
                    decision="acceptance_criteria_not_declared",
                )
            attempts = int(anchor["quality_attempt_count"])
            if attempts >= int(anchor["quality_max_attempts"]):
                return self._finish_quality_validation(
                    anchor_id, now, state="quality_validation_failed", error=exc.code
                )
            delay = min(300, self.default_poll_seconds * (2 ** min(attempts - 1, 5)))
            return self._finish_quality_validation(
                anchor_id,
                now,
                state="delivery_verified",
                error=exc.code,
                next_run_at=now + delay,
            )
        except Exception:
            return self._finish_quality_validation(
                anchor_id,
                now,
                state="quality_validation_failed",
                error="unexpected_quality_validation_failure",
            )
        final_state = (
            "quality_accepted"
            if decision == "accepted_by_explicit_criteria"
            else "quality_rejected"
        )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = ?, quality_lease_until = NULL, quality_error = NULL,
                       quality_validation_id = ?, quality_validation_sha256 = ?,
                       quality_decision = ?, quality_criteria_sha256 = ?,
                       quality_passed_count = ?, quality_failed_count = ?,
                       quality_validated_at = ?, updated_at = ? WHERE anchor_id = ?""",
                (
                    final_state,
                    str(quality["quality_validation_id"]),
                    str(quality["quality_validation_sha256"]),
                    decision,
                    str(quality.get("criteria_sha256") or ""),
                    int(quality.get("passed_count") or 0),
                    int(quality.get("failed_count") or 0),
                    int(quality.get("evaluated_at") or now),
                    now,
                    anchor_id,
                ),
            )
            connection.execute(
                """UPDATE buyer_agent_job_anchors SET eligibility_next_run_at = ?
                   WHERE anchor_id = ?""",
                (now, anchor_id),
            )
        return {"work_type": "quality_validation", **self.get_anchor(
            str(anchor["intent_decision_id"])
        )}

    def _finish_quality_validation(
        self,
        anchor_id: str,
        now: int,
        *,
        state: str,
        error: str | None,
        decision: str | None = None,
        next_run_at: int | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = ?, quality_next_run_at = ?, quality_lease_until = NULL,
                       quality_error = ?, quality_decision = COALESCE(?, quality_decision),
                       updated_at = ? WHERE anchor_id = ?""",
                (state, next_run_at or now, error, decision, now, anchor_id),
            )
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        return {"work_type": "quality_validation", **dict(row)}

    def _claim_validation(self, now: int) -> str | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT anchor_id, validation_attempt_count,
                          validation_max_attempts
                   FROM buyer_agent_job_anchors
                   WHERE (state = 'published' AND validation_next_run_at <= ?)
                      OR (state = 'validating' AND validation_lease_until IS NOT NULL
                          AND validation_lease_until <= ?)
                   ORDER BY validation_next_run_at, created_at LIMIT 1""",
                (now, now),
            ).fetchone()
            if row is None:
                return None
            anchor_id = str(row["anchor_id"])
            if int(row["validation_attempt_count"]) >= int(
                row["validation_max_attempts"]
            ):
                connection.execute(
                    """UPDATE buyer_agent_job_anchors
                       SET state = 'validation_failed', validation_lease_until = NULL,
                           updated_at = ?, validation_error =
                           'maximum_validation_attempts_reached'
                       WHERE anchor_id = ?""",
                    (now, anchor_id),
                )
                return anchor_id
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'validating', validation_lease_until = ?, updated_at = ?,
                       validation_attempt_count = validation_attempt_count + 1
                   WHERE anchor_id = ?""",
                (now + self.lease_seconds, now, anchor_id),
            )
            return anchor_id

    def _run_validation(self, anchor_id: str, now: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        anchor = dict(row)
        if anchor["state"] == "validation_failed":
            return {"work_type": "delivery_validation", **anchor}
        try:
            validation = self.runner.validate_delivery_evidence(anchor["receipt_id"])
            decision = str(validation.get("decision") or "")
            bindings = (
                str(validation.get("evidence_receipt_id") or "")
                == str(anchor["receipt_id"])
                and decision
                in {"verified_delivery_binding", "rejected_delivery_binding"}
                and validation.get("effect") == "evidence_only"
                and validation.get("quality_verified") is False
                and str(validation.get("validation_id") or "").startswith("pdv_")
                and len(str(validation.get("validation_sha256") or "")) == 64
            )
            if not bindings:
                raise AutonomousBuyerError("protocol_delivery_validation_mismatch")
        except AutonomousBuyerError as exc:
            attempts = int(anchor["validation_attempt_count"])
            if attempts >= int(anchor["validation_max_attempts"]):
                return self._finish_validation(
                    anchor_id, now, state="validation_failed", error=exc.code
                )
            delay = min(300, self.default_poll_seconds * (2 ** min(attempts - 1, 5)))
            return self._finish_validation(
                anchor_id,
                now,
                state="published",
                error=exc.code,
                next_run_at=now + delay,
            )
        except Exception:
            return self._finish_validation(
                anchor_id,
                now,
                state="validation_failed",
                error="unexpected_validation_failure",
            )
        final_state = (
            "delivery_verified"
            if decision == "verified_delivery_binding"
            else "delivery_rejected"
        )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = ?, validation_lease_until = NULL,
                       validation_error = NULL, validation_id = ?,
                       validation_sha256 = ?, validation_decision = ?,
                       validation_reason = ?, validated_at = ?, updated_at = ?
                   WHERE anchor_id = ?""",
                (
                    final_state,
                    str(validation["validation_id"]),
                    str(validation["validation_sha256"]),
                    decision,
                    str(validation.get("reason") or ""),
                    int(validation.get("evaluated_at") or now),
                    now,
                    anchor_id,
                ),
            )
            if final_state == "delivery_verified":
                connection.execute(
                    """UPDATE buyer_agent_job_anchors SET quality_next_run_at = ?
                       WHERE anchor_id = ?""",
                    (now, anchor_id),
                )
        return {"work_type": "delivery_validation", **self.get_anchor(
            str(anchor["intent_decision_id"])
        )}

    def _finish_validation(
        self,
        anchor_id: str,
        now: int,
        *,
        state: str,
        error: str,
        next_run_at: int | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = ?, validation_next_run_at = ?,
                       validation_lease_until = NULL, validation_error = ?,
                       updated_at = ? WHERE anchor_id = ?""",
                (state, next_run_at or now, error, now, anchor_id),
            )
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        return {"work_type": "delivery_validation", **dict(row)}

    def _claim_publication(self, now: int) -> str | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT anchor_id, publication_attempt_count,
                          publication_max_attempts
                   FROM buyer_agent_job_anchors
                   WHERE (state = 'attested' AND publication_next_run_at <= ?)
                      OR (state = 'publishing' AND publication_lease_until IS NOT NULL
                          AND publication_lease_until <= ?)
                   ORDER BY publication_next_run_at, created_at LIMIT 1""",
                (now, now),
            ).fetchone()
            if row is None:
                return None
            anchor_id = str(row["anchor_id"])
            if int(row["publication_attempt_count"]) >= int(
                row["publication_max_attempts"]
            ):
                connection.execute(
                    """UPDATE buyer_agent_job_anchors
                       SET state = 'publication_failed', publication_lease_until = NULL,
                           updated_at = ?, publication_error =
                           'maximum_publication_attempts_reached'
                       WHERE anchor_id = ?""",
                    (now, anchor_id),
                )
                return anchor_id
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'publishing', publication_lease_until = ?, updated_at = ?,
                       publication_attempt_count = publication_attempt_count + 1
                   WHERE anchor_id = ?""",
                (now + self.lease_seconds, now, anchor_id),
            )
            return anchor_id

    def _run_publication(self, anchor_id: str, now: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        anchor = dict(row)
        if anchor["state"] == "publication_failed":
            return {"work_type": "evidence_publication", **anchor}
        try:
            receipt = self.runner.publish_evidence(
                {
                    "evidence_type": "buyer_job_journal",
                    "evidence_id": anchor["intent_decision_id"],
                    "evidence_sha256": anchor["evidence_sha256"],
                    "observed_at": anchor["observed_at"],
                    "wallet_address": anchor["wallet_address"],
                    "signature": anchor["signature"],
                }
            )
            bindings = (
                str(receipt.get("evidence_id") or "") == str(anchor["intent_decision_id"])
                and str(receipt.get("evidence_sha256") or "")
                == str(anchor["evidence_sha256"])
                and str(receipt.get("wallet_address") or "")
                == str(anchor["wallet_address"])
                and str(receipt.get("signature") or "") == str(anchor["signature"])
                and str(receipt.get("observed_at") or "") == str(anchor["observed_at"])
                and receipt.get("effect") == "evidence_only"
                and str(receipt.get("receipt_id") or "").startswith("per_")
                and len(str(receipt.get("receipt_sha256") or "")) == 64
            )
            if not bindings:
                raise AutonomousBuyerError("protocol_evidence_receipt_mismatch")
        except AutonomousBuyerError as exc:
            attempts = int(anchor["publication_attempt_count"])
            if attempts >= int(anchor["publication_max_attempts"]):
                return self._finish_publication(
                    anchor_id, now, state="publication_failed", error=exc.code
                )
            delay = min(300, self.default_poll_seconds * (2 ** min(attempts - 1, 5)))
            return self._finish_publication(
                anchor_id,
                now,
                state="attested",
                error=exc.code,
                next_run_at=now + delay,
            )
        except Exception:
            return self._finish_publication(
                anchor_id,
                now,
                state="publication_failed",
                error="unexpected_publication_failure",
            )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'published', publication_lease_until = NULL,
                       publication_error = NULL, receipt_id = ?, receipt_sha256 = ?,
                       published_at = ?, validation_next_run_at = ?, updated_at = ?
                   WHERE anchor_id = ?""",
                (
                    str(receipt["receipt_id"]),
                    str(receipt["receipt_sha256"]),
                    int(receipt.get("received_at") or now),
                    now,
                    now,
                    anchor_id,
                ),
            )
        return {"work_type": "evidence_publication", **self.get_anchor(
            str(anchor["intent_decision_id"])
        )}

    def _finish_publication(
        self,
        anchor_id: str,
        now: int,
        *,
        state: str,
        error: str,
        next_run_at: int | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = ?, publication_next_run_at = ?,
                       publication_lease_until = NULL, publication_error = ?,
                       updated_at = ? WHERE anchor_id = ?""",
                (state, next_run_at or now, error, now, anchor_id),
            )
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        return {"work_type": "evidence_publication", **dict(row)}

    def _claim_anchor(self, now: int) -> str | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT anchor_id, attempt_count, max_attempts
                   FROM buyer_agent_job_anchors
                   WHERE (state = 'pending' AND next_run_at <= ?)
                      OR (state = 'attesting' AND lease_until IS NOT NULL AND lease_until <= ?)
                   ORDER BY next_run_at, created_at LIMIT 1""",
                (now, now),
            ).fetchone()
            if row is None:
                return None
            anchor_id = str(row["anchor_id"])
            if int(row["attempt_count"]) >= int(row["max_attempts"]):
                connection.execute(
                    """UPDATE buyer_agent_job_anchors
                       SET state = 'failed', lease_until = NULL, updated_at = ?,
                           last_error = 'maximum_attestation_attempts_reached'
                       WHERE anchor_id = ?""",
                    (now, anchor_id),
                )
                return anchor_id
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'attesting', lease_until = ?, updated_at = ?,
                       attempt_count = attempt_count + 1
                   WHERE anchor_id = ?""",
                (now + self.lease_seconds, now, anchor_id),
            )
            return anchor_id

    def _run_anchor(self, anchor_id: str, now: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        anchor = dict(row)
        if anchor["state"] == "failed":
            return {"work_type": "evidence_anchor", **anchor}
        decision_id = str(anchor["intent_decision_id"])
        verification = self.verify_event_chain(decision_id)
        if (
            verification.get("valid") is not True
            or not hmac.compare_digest(
                str(verification.get("head_hash") or ""),
                str(anchor["evidence_sha256"]),
            )
        ):
            return self._finish_anchor(
                anchor_id,
                now,
                state="failed",
                error="journal_chain_verification_failed",
            )
        try:
            result = self.runner.wallet.attest_evidence(
                evidence_type="buyer_job_journal",
                evidence_id=decision_id,
                evidence_sha256=str(anchor["evidence_sha256"]),
                observed_at=now,
            )
            signature = Signature.from_string(str(result.get("signature") or ""))
            wallet_address = str(result.get("wallet_address") or "")
            message = build_evidence_message(
                wallet_address,
                "buyer_job_journal",
                decision_id,
                str(anchor["evidence_sha256"]),
                now,
            )
            bindings = (
                hmac.compare_digest(wallet_address, str(self.runner.wallet.wallet_address))
                and hmac.compare_digest(str(result.get("evidence_id") or ""), decision_id)
                and hmac.compare_digest(
                    str(result.get("evidence_sha256") or ""),
                    str(anchor["evidence_sha256"]),
                )
                and str(result.get("observed_at") or "") == str(now)
                and signature.verify(Pubkey.from_string(wallet_address), message)
            )
            if not bindings:
                raise WalletAdapterError("wallet_evidence_binding_mismatch")
        except (WalletAdapterError, ValueError) as exc:
            code = str(getattr(exc, "code", "wallet_evidence_invalid"))
            attempts = int(anchor["attempt_count"])
            if attempts >= int(anchor["max_attempts"]):
                return self._finish_anchor(anchor_id, now, state="failed", error=code)
            delay = min(300, self.default_poll_seconds * (2 ** min(attempts - 1, 5)))
            return self._finish_anchor(
                anchor_id,
                now,
                state="pending",
                error=code,
                next_run_at=now + delay,
            )
        except Exception:
            return self._finish_anchor(
                anchor_id,
                now,
                state="failed",
                error="unexpected_attestation_failure",
            )
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = 'attested', lease_until = NULL, observed_at = ?,
                       wallet_address = ?, signature = ?, last_error = NULL,
                       publication_next_run_at = ?,
                       updated_at = ? WHERE anchor_id = ?""",
                (now, wallet_address, str(signature), now, now, anchor_id),
            )
        return {"work_type": "evidence_anchor", **self.get_anchor(decision_id)}

    def _finish_anchor(
        self,
        anchor_id: str,
        now: int,
        *,
        state: str,
        error: str,
        next_run_at: int | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """UPDATE buyer_agent_job_anchors
                   SET state = ?, next_run_at = ?, lease_until = NULL,
                       last_error = ?, updated_at = ? WHERE anchor_id = ?""",
                (state, next_run_at or now, error, now, anchor_id),
            )
            row = connection.execute(
                "SELECT * FROM buyer_agent_job_anchors WHERE anchor_id = ?",
                (anchor_id,),
            ).fetchone()
        return {"work_type": "evidence_anchor", **dict(row)}

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
            if state == "completed":
                head = connection.execute(
                    """SELECT event_head_hash FROM buyer_agent_jobs
                       WHERE intent_decision_id = ?""",
                    (decision_id,),
                ).fetchone()[0]
                anchor_id = "bea_" + hashlib.sha256(
                    f"{decision_id}:{head}".encode("utf-8")
                ).hexdigest()[:24]
                connection.execute(
                    """INSERT INTO buyer_agent_job_anchors (
                           anchor_id, intent_decision_id, evidence_sha256,
                           state, next_run_at, created_at, updated_at
                       ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
                       ON CONFLICT(intent_decision_id) DO NOTHING""",
                    (anchor_id, decision_id, head, now, now, now),
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
        row = connection.execute(
            """SELECT event_hash FROM buyer_agent_job_events
               WHERE intent_decision_id = ? ORDER BY event_id DESC LIMIT 1""",
            (intent_decision_id,),
        ).fetchone()
        previous_hash = str(row["event_hash"]) if row is not None else GENESIS_EVENT_HASH
        if len(previous_hash) != 64:
            raise RuntimeError("buyer_agent_event_chain_unavailable")
        event = {
            "intent_decision_id": intent_decision_id,
            "event_type": event_type,
            "state": state,
            "action": action,
            "error": error,
            "created_at": created_at,
        }
        event_hash = BuyerAgentScheduler._event_hash(event, previous_hash)
        connection.execute(
            """INSERT INTO buyer_agent_job_events (
                   intent_decision_id, event_type, state, action, error, created_at,
                   previous_hash, event_hash
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                intent_decision_id,
                event_type,
                state,
                action,
                error,
                created_at,
                previous_hash,
                event_hash,
            ),
        )
        connection.execute(
            """UPDATE buyer_agent_jobs
               SET event_count = event_count + 1, event_head_hash = ?
               WHERE intent_decision_id = ?""",
            (event_hash, intent_decision_id),
        )

    @staticmethod
    def _event_hash(event: dict[str, Any], previous_hash: str) -> str:
        canonical = json.dumps(
            {
                "version": 1,
                "intent_decision_id": str(event["intent_decision_id"]),
                "event_type": str(event["event_type"]),
                "state": str(event["state"]),
                "action": event.get("action"),
                "error": event.get("error"),
                "created_at": int(event["created_at"]),
                "previous_hash": previous_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def _backfill_event_hashes(
        cls,
        connection: sqlite3.Connection,
    ) -> None:
        rows = connection.execute(
            """SELECT event_id, intent_decision_id, event_type, state,
                      action, error, created_at
               FROM buyer_agent_job_events
               ORDER BY intent_decision_id ASC, event_id ASC"""
        ).fetchall()
        previous_by_intent: dict[str, str] = {}
        count_by_intent: dict[str, int] = {}
        for row in rows:
            event = dict(row)
            decision_id = str(event["intent_decision_id"])
            previous_hash = previous_by_intent.get(decision_id, GENESIS_EVENT_HASH)
            event_hash = cls._event_hash(event, previous_hash)
            connection.execute(
                """UPDATE buyer_agent_job_events
                   SET previous_hash = ?, event_hash = ? WHERE event_id = ?""",
                (previous_hash, event_hash, event["event_id"]),
            )
            previous_by_intent[decision_id] = event_hash
            count_by_intent[decision_id] = count_by_intent.get(decision_id, 0) + 1
        for decision_id, event_hash in previous_by_intent.items():
            connection.execute(
                """UPDATE buyer_agent_jobs
                   SET event_count = ?, event_head_hash = ?
                   WHERE intent_decision_id = ?""",
                (count_by_intent[decision_id], event_hash, decision_id),
            )

    @staticmethod
    def _verification_result(
        intent_decision_id: str,
        events: list[dict[str, Any]],
        invalid_event_id: int | None,
    ) -> dict[str, Any]:
        return {
            "status": "buyer_agent_event_chain_invalid",
            "intent_decision_id": intent_decision_id,
            "valid": False,
            "event_count": len(events),
            "head_hash": None,
            "first_invalid_event_id": (
                int(invalid_event_id) if invalid_event_id is not None else None
            ),
        }

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
