"""Durable post-payment delivery for universal checkout.

Payment finality and service delivery are deliberately separate state
machines. A provider failure must never make a finalized payment disappear or
cause its transaction signature to be consumed twice.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from typing import Any, Callable

from iat.api import db as database
from iat.api.db import get_conn, get_order_db, qmark, release_conn


TERMINAL_STATES = {"completed", "review_required", "blocked", "exhausted"}
RUNNABLE_STATES = {"pending", "retryable_failure", "running"}
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False
AUTHORIZED_DELIVERY_STATUSES = {
    "consensus_delivered",
    "seller_runtime_consensus_delivered",
    "foundation_supplier_pipeline_completed",
    "foundation_supplier_pipeline_fallback",
    "pipeline_completed",
    "success",
}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def init_checkout_delivery_db() -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS universal_checkout_deliveries (
                quote_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL UNIQUE,
                tx_signature TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at INTEGER NOT NULL,
                lease_token TEXT,
                lease_until INTEGER,
                last_error_code TEXT,
                result_payload TEXT,
                settlement_state TEXT NOT NULL DEFAULT 'pending',
                settlement_attempt_count INTEGER NOT NULL DEFAULT 0,
                settlement_next_attempt_at INTEGER,
                settlement_error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                completed_at INTEGER
            )
            """
        )
        settlement_columns = {
            "settlement_state": "TEXT NOT NULL DEFAULT 'pending'",
            "settlement_attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "settlement_next_attempt_at": "INTEGER",
            "settlement_error": "TEXT",
        }
        for column, definition in settlement_columns.items():
            try:
                if database.USE_POSTGRES:
                    cur.execute(
                        f"ALTER TABLE universal_checkout_deliveries "
                        f"ADD COLUMN IF NOT EXISTS {column} {definition}"
                    )
                else:
                    cur.execute(
                        f"ALTER TABLE universal_checkout_deliveries "
                        f"ADD COLUMN {column} {definition}"
                    )
            except Exception:
                pass
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_checkout_delivery_runnable
            ON universal_checkout_deliveries (state, next_attempt_at)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS universal_checkout_delivery_events (
                event_id TEXT PRIMARY KEY,
                quote_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT,
                actor TEXT NOT NULL,
                reason TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_checkout_delivery_events_quote
            ON universal_checkout_delivery_events (quote_id, created_at)
            """
        )
        conn.commit()
    finally:
        release_conn(conn)


def enqueue_delivery_tx(
    cur: Any,
    *,
    quote_id: str,
    order_id: str,
    tx_signature: str,
    now: int,
) -> None:
    """Enqueue using the caller's payment-finalization transaction."""
    p = qmark()
    if database.USE_POSTGRES:
        cur.execute(
            f"""
            INSERT INTO universal_checkout_deliveries (
                quote_id, order_id, tx_signature, state, attempt_count,
                next_attempt_at, created_at, updated_at
            ) VALUES ({p}, {p}, {p}, {p}, 0, {p}, {p}, {p})
            ON CONFLICT (quote_id) DO NOTHING
            """,
            (quote_id, order_id, tx_signature, "pending", now, now, now),
        )
    else:
        cur.execute(
            f"""
            INSERT OR IGNORE INTO universal_checkout_deliveries (
                quote_id, order_id, tx_signature, state, attempt_count,
                next_attempt_at, created_at, updated_at
            ) VALUES ({p}, {p}, {p}, {p}, 0, {p}, {p}, {p})
            """,
            (quote_id, order_id, tx_signature, "pending", now, now, now),
        )
    if cur.rowcount == 1:
        _insert_event(
            cur,
            quote_id=quote_id,
            order_id=order_id,
            event_type="payment_confirmed_delivery_enqueued",
            from_state=None,
            to_state="pending",
            actor="protocol",
            reason=None,
            now=now,
        )


def _insert_event(
    cur: Any,
    *,
    quote_id: str,
    order_id: str,
    event_type: str,
    from_state: str | None,
    to_state: str,
    actor: str,
    reason: str | None,
    now: int,
) -> None:
    p = qmark()
    cur.execute(
        f"""
        INSERT INTO universal_checkout_delivery_events (
            event_id, quote_id, order_id, event_type, from_state,
            to_state, actor, reason, created_at
        ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """,
        (
            f"cde_{secrets.token_hex(16)}",
            quote_id,
            order_id,
            event_type,
            from_state,
            to_state,
            actor[:128],
            reason,
            now,
        ),
    )
def get_delivery(quote_id: str) -> dict[str, Any] | None:
    init_checkout_delivery_db()
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"SELECT * FROM universal_checkout_deliveries WHERE quote_id = {p}",
            (quote_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        delivery = dict(row)
        raw_result = delivery.pop("result_payload", None)
        if raw_result:
            try:
                delivery["result"] = json.loads(raw_result)
            except (TypeError, json.JSONDecodeError):
                delivery["result"] = {"status": "unreadable_result"}
        return delivery
    finally:
        release_conn(conn)


def _public_delivery(delivery: dict[str, Any] | None) -> dict[str, Any]:
    if not delivery:
        return {"state": "not_enqueued"}
    result = {
        key: delivery.get(key)
        for key in (
            "state",
            "attempt_count",
            "next_attempt_at",
            "last_error_code",
            "updated_at",
            "completed_at",
            "settlement_state",
            "settlement_attempt_count",
            "settlement_next_attempt_at",
            "settlement_error",
        )
    }
    raw_result = delivery.get("result")
    if isinstance(raw_result, dict):
        allowed_result_fields = {
            "status",
            "summary",
            "recommendations",
            "final_recommendation",
            "confidence",
            "sources",
            "message",
            "reason",
            "delivery_authorized",
            "foundation_verdict",
            "foundation_decision_ready",
            "foundation_evidence_status",
            "foundation_evidence_reason",
            "research_status",
            "research_valid_agents",
            "verification_status",
            "verification_valid_agents",
            "claim_validation_status",
            "verified_claim_count",
            "rejected_claim_count",
            "execution_mode",
            "retryable",
        }
        result["result"] = {
            key: raw_result[key]
            for key in allowed_result_fields
            if key in raw_result
        }
    result["retryable"] = delivery.get("state") == "retryable_failure"
    return result


def public_delivery_status(quote_id: str) -> dict[str, Any]:
    return _public_delivery(get_delivery(quote_id))


def list_due_deliveries(*, now: int | None = None, limit: int = 20) -> list[str]:
    init_checkout_delivery_db()
    current_time = int(time.time()) if now is None else int(now)
    safe_limit = max(1, min(int(limit), 100))
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            SELECT quote_id FROM universal_checkout_deliveries
            WHERE (state IN ({p}, {p}) AND next_attempt_at <= {p})
               OR (state = {p} AND lease_until < {p})
            ORDER BY next_attempt_at ASC, created_at ASC
            LIMIT {p}
            """,
            (
                "pending",
                "retryable_failure",
                current_time,
                "running",
                current_time,
                safe_limit,
            ),
        )
        return [str(dict(row)["quote_id"]) for row in cur.fetchall()]
    finally:
        release_conn(conn)


def delivery_dashboard(*, limit: int = 50) -> dict[str, Any]:
    """Return operational metadata without buyer payloads or credentials."""
    init_checkout_delivery_db()
    safe_limit = max(1, min(int(limit), 200))
    now = int(time.time())
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT state, COUNT(*) AS count
            FROM universal_checkout_deliveries
            GROUP BY state
            """
        )
        state_counts = {
            str(dict(row)["state"]): int(dict(row)["count"])
            for row in cur.fetchall()
        }
        p = qmark()
        cur.execute(
            f"""
            SELECT quote_id, order_id, state, attempt_count, next_attempt_at,
                   lease_until, last_error_code, created_at, updated_at,
                   completed_at, settlement_state, settlement_attempt_count,
                   settlement_next_attempt_at, settlement_error
            FROM universal_checkout_deliveries
            ORDER BY
                CASE WHEN state IN ({p}, {p}, {p}) THEN 0 ELSE 1 END,
                updated_at ASC
            LIMIT {p}
            """,
            ("exhausted", "retryable_failure", "running", safe_limit),
        )
        items = [dict(row) for row in cur.fetchall()]
        due_count = sum(
            1
            for item in items
            if item["state"] in {"pending", "retryable_failure"}
            and int(item["next_attempt_at"]) <= now
        )
        stale_leases = sum(
            1
            for item in items
            if item["state"] == "running"
            and int(item.get("lease_until") or 0) < now
        )
        return {
            "status": "ok",
            "generated_at": now,
            "state_counts": state_counts,
            "total": sum(state_counts.values()),
            "due_in_result_window": due_count,
            "stale_leases_in_result_window": stale_leases,
            "worker_enabled": os.getenv(
                "IAT_CHECKOUT_DELIVERY_WORKER_ENABLED", "true"
            ).strip().lower() in {"1", "true", "yes", "on"},
            "items": items,
        }
    finally:
        release_conn(conn)


def delivery_events(quote_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    init_checkout_delivery_db()
    safe_limit = max(1, min(int(limit), 500))
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            SELECT event_id, quote_id, order_id, event_type, from_state,
                   to_state, actor, reason, created_at
            FROM universal_checkout_delivery_events
            WHERE quote_id = {p}
            ORDER BY created_at DESC
            LIMIT {p}
            """,
            (quote_id, safe_limit),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        release_conn(conn)


def redrive_exhausted_delivery(
    quote_id: str,
    *,
    reason: str,
    actor: str = "admin_api_key",
    now: int | None = None,
) -> dict[str, Any]:
    """Explicitly reopen a terminal technical failure, with an audit event."""
    clean_reason = " ".join(str(reason or "").split())
    if not 8 <= len(clean_reason) <= 500:
        raise ValueError("redrive_reason_length_invalid")
    current_time = int(time.time()) if now is None else int(now)
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            SELECT order_id, state FROM universal_checkout_deliveries
            WHERE quote_id = {p}
            """,
            (quote_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("delivery_not_found")
        current = dict(row)
        if current["state"] != "exhausted":
            raise ValueError("delivery_not_exhausted")
        cur.execute(
            f"""
            UPDATE universal_checkout_deliveries
            SET state = {p}, attempt_count = 0, next_attempt_at = {p},
                lease_token = NULL, lease_until = NULL,
                last_error_code = NULL, completed_at = NULL, updated_at = {p}
            WHERE quote_id = {p} AND state = {p}
            """,
            ("pending", current_time, current_time, quote_id, "exhausted"),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise ValueError("delivery_redrive_conflict")
        cur.execute(
            f"""
            INSERT INTO universal_checkout_delivery_events (
                event_id, quote_id, order_id, event_type, from_state,
                to_state, actor, reason, created_at
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """,
            (
                f"cde_{secrets.token_hex(16)}",
                quote_id,
                current["order_id"],
                "admin_redrive",
                "exhausted",
                "pending",
                actor[:128],
                clean_reason,
                current_time,
            ),
        )
        conn.commit()
    finally:
        release_conn(conn)
    return {
        "status": "redrive_scheduled",
        "quote_id": quote_id,
        "state": "pending",
        "next_attempt_at": current_time,
    }


def resume_review_required_delivery(
    quote_id: str,
    *,
    actor: str = "authenticated_buyer",
    now: int | None = None,
) -> dict[str, Any]:
    """Reopen a legacy review state without resetting its attempt budget.

    New incomplete Foundation decisions use the normal automatic retry path.
    This transition exists so deliveries created by older releases are not
    stranded forever in the former terminal ``review_required`` state.
    """
    current_time = int(time.time()) if now is None else int(now)
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            SELECT order_id, state FROM universal_checkout_deliveries
            WHERE quote_id = {p}
            """,
            (quote_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("delivery_not_found")
        current = dict(row)
        if current["state"] != "review_required":
            return {
                "status": "resume_not_required",
                "quote_id": quote_id,
                "state": current["state"],
                "next_attempt_at": current_time,
                "idempotent": True,
            }
        cur.execute(
            f"""
            UPDATE universal_checkout_deliveries
            SET state = {p}, next_attempt_at = {p}, lease_token = NULL,
                lease_until = NULL, completed_at = NULL, updated_at = {p}
            WHERE quote_id = {p} AND state = {p}
            """,
            ("retryable_failure", current_time, current_time, quote_id, "review_required"),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise ValueError("delivery_resume_conflict")
        _insert_event(
            cur,
            quote_id=quote_id,
            order_id=current["order_id"],
            event_type="legacy_review_resumed",
            from_state="review_required",
            to_state="retryable_failure",
            actor=actor[:128],
            reason="autonomous_delivery_policy_upgrade",
            now=current_time,
        )
        conn.commit()
    finally:
        release_conn(conn)
    return {
        "status": "review_resumed",
        "quote_id": quote_id,
        "state": "retryable_failure",
        "next_attempt_at": current_time,
        "idempotent": False,
    }


def _claim(quote_id: str, now: int) -> tuple[dict[str, Any] | None, str | None]:
    lease_seconds = _int_env("IAT_CHECKOUT_DELIVERY_LEASE_SECONDS", 90, 30, 900)
    token = secrets.token_urlsafe(24)
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            UPDATE universal_checkout_deliveries
            SET state = {p}, lease_token = {p}, lease_until = {p},
                attempt_count = attempt_count + 1, updated_at = {p}
            WHERE quote_id = {p}
              AND (
                    (state IN ({p}, {p}) AND next_attempt_at <= {p})
                    OR (state = {p} AND lease_until < {p})
                  )
            """,
            (
                "running",
                token,
                now + lease_seconds,
                now,
                quote_id,
                "pending",
                "retryable_failure",
                now,
                "running",
                now,
            ),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return get_delivery(quote_id), None
        cur.execute(
            f"""
            SELECT order_id FROM universal_checkout_deliveries
            WHERE quote_id = {p}
            """,
            (quote_id,),
        )
        claimed_row = cur.fetchone()
        _insert_event(
            cur,
            quote_id=quote_id,
            order_id=str(dict(claimed_row)["order_id"]),
            event_type="delivery_attempt_claimed",
            from_state="runnable",
            to_state="running",
            actor="delivery_worker",
            reason=None,
            now=now,
        )
        conn.commit()
        return get_delivery(quote_id), token
    finally:
        release_conn(conn)


def _finish(
    quote_id: str,
    lease_token: str,
    *,
    state: str,
    now: int,
    result: dict[str, Any] | None,
    error_code: str | None = None,
    next_attempt_at: int | None = None,
    settlement_state: str | None = None,
    settlement_next_attempt_at: int | None = None,
    settlement_error: str | None = None,
) -> bool:
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        completed_at = now if state in TERMINAL_STATES else None
        cur.execute(
            f"""
            UPDATE universal_checkout_deliveries
            SET state = {p}, next_attempt_at = {p}, lease_token = NULL,
                lease_until = NULL, last_error_code = {p},
                result_payload = {p}, updated_at = {p}, completed_at = {p},
                settlement_state = COALESCE({p}, settlement_state),
                settlement_next_attempt_at = {p}, settlement_error = {p}
            WHERE quote_id = {p} AND state = {p} AND lease_token = {p}
            """,
            (
                state,
                next_attempt_at if next_attempt_at is not None else now,
                error_code,
                json.dumps(result, sort_keys=True) if result is not None else None,
                now,
                completed_at,
                settlement_state,
                settlement_next_attempt_at,
                settlement_error,
                quote_id,
                "running",
                lease_token,
            ),
        )
        changed = cur.rowcount == 1
        if changed:
            cur.execute(
                f"""
                SELECT order_id FROM universal_checkout_deliveries
                WHERE quote_id = {p}
                """,
                (quote_id,),
            )
            event_row = cur.fetchone()
            _insert_event(
                cur,
                quote_id=quote_id,
                order_id=str(dict(event_row)["order_id"]),
                event_type="delivery_attempt_finished",
                from_state="running",
                to_state=state,
                actor="delivery_worker",
                reason=error_code,
                now=now,
            )
        conn.commit()
        return changed
    finally:
        release_conn(conn)


def _mark_order(order_id: str, tx_signature: str, state: str, result: dict[str, Any]) -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())
        if state == "completed":
            cur.execute(
                f"""
                UPDATE orders SET status = {p}, tx_signature = {p},
                    updated_at = {p}, delivered_at = {p},
                    delivery_result = {p}, used = {p}
                WHERE order_id = {p} AND used = {p}
                """,
                (
                    "delivered",
                    tx_signature,
                    now,
                    now,
                    json.dumps(result, sort_keys=True),
                    1,
                    order_id,
                    0,
                ),
            )
        else:
            order_status = {
                "review_required": "foundation_review_required",
                "blocked": "foundation_delivery_blocked",
            }[state]
            cur.execute(
                f"""
                UPDATE orders SET status = {p}, tx_signature = {p},
                    updated_at = {p}, delivery_result = {p}
                WHERE order_id = {p} AND used = {p}
                """,
                (
                    order_status,
                    tx_signature,
                    now,
                    json.dumps(result, sort_keys=True),
                    order_id,
                    0,
                ),
            )
        conn.commit()
    finally:
        release_conn(conn)


def _request_protocol_compensation(quote_id: str) -> None:
    try:
        from iat.checkout_compensation import request_compensation

        request_compensation(quote_id, requested_by="delivery_state_machine")
    except Exception:
        # Compensation remains buyer-requestable and visible as absent. A
        # transient database error must not corrupt the delivery transition.
        pass


def run_checkout_delivery(
    quote_id: str,
    *,
    executor: Callable[[dict[str, Any], str], Any] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Run one due delivery attempt.

    The stable ``order_id`` and ``tx_signature`` form the downstream
    idempotency identity. Providers must honor that identity because no
    distributed system can guarantee exactly-once external side effects after
    a worker crash.
    """
    init_checkout_delivery_db()
    current_time = int(time.time()) if now is None else int(now)
    claimed, lease_token = _claim(quote_id, current_time)
    if not claimed:
        return {"state": "not_enqueued", "payment_verified": False}
    if not lease_token:
        return {**_public_delivery(claimed), "claimed": False}

    order = get_order_db(claimed["order_id"])
    if not order:
        _finish(
            quote_id,
            lease_token,
            state="exhausted",
            now=current_time,
            result={"status": "order_missing"},
            error_code="order_missing",
        )
        return public_delivery_status(quote_id)
    if order.get("used") or str(order.get("status") or "").lower() == "delivered":
        _finish(
            quote_id,
            lease_token,
            state="completed",
            now=current_time,
            result=order.get("delivery_result") or {"status": "already_delivered"},
        )
        return public_delivery_status(quote_id)

    if executor is None:
        from iat.action_engine.protocol_runtime import execute_protocol_order

        executor = execute_protocol_order

    try:
        raw_result = executor(order, claimed["tx_signature"])
        result = raw_result if isinstance(raw_result, dict) else {
            "status": "invalid_delivery_result",
        }
    except Exception:
        result = {"status": "provider_execution_exception"}

    status = str(result.get("status") or "").strip().lower()
    if status == "foundation_review_required":
        attempts = int(claimed.get("attempt_count") or 1)
        max_attempts = _int_env("IAT_CHECKOUT_DELIVERY_MAX_ATTEMPTS", 8, 1, 32)
        if attempts >= max_attempts:
            _mark_order(claimed["order_id"], claimed["tx_signature"], "review_required", result)
            _finish(
                quote_id,
                lease_token,
                state="exhausted",
                now=current_time,
                result=result,
                error_code="foundation_decision_not_ready_for_delivery",
                next_attempt_at=current_time,
            )
            _request_protocol_compensation(quote_id)
        else:
            base = _int_env("IAT_CHECKOUT_DELIVERY_RETRY_BASE_SECONDS", 30, 5, 3600)
            delay = min(base * (2 ** (attempts - 1)), 3600)
            _finish(
                quote_id,
                lease_token,
                state="retryable_failure",
                now=current_time,
                result=result,
                error_code="foundation_decision_not_ready_for_delivery",
                next_attempt_at=current_time + delay,
            )
    elif status == "foundation_delivery_blocked":
        _mark_order(claimed["order_id"], claimed["tx_signature"], "blocked", result)
        _finish(
            quote_id,
            lease_token,
            state="blocked",
            now=current_time,
            result=result,
        )
        _request_protocol_compensation(quote_id)
    elif not result.get("error") and status in AUTHORIZED_DELIVERY_STATUSES:
        settlement_state = "completed"
        settlement_error = None
        try:
            from iat.checkout_settlement import allocate_checkout_settlement

            result = {
                **result,
                "settlement": allocate_checkout_settlement(order, result),
            }
        except Exception:
            settlement_state = "retryable_failure"
            settlement_error = "settlement_allocation_error"
            result = {
                **result,
                "settlement": {
                    "status": "allocation_error",
                    "retryable": True,
                },
            }
        _mark_order(claimed["order_id"], claimed["tx_signature"], "completed", result)
        _finish(
            quote_id,
            lease_token,
            state="completed",
            now=current_time,
            result=result,
            settlement_state=settlement_state,
            settlement_next_attempt_at=(
                current_time + 30 if settlement_state == "retryable_failure" else None
            ),
            settlement_error=settlement_error,
        )
    else:
        attempts = int(claimed.get("attempt_count") or 1)
        max_attempts = _int_env("IAT_CHECKOUT_DELIVERY_MAX_ATTEMPTS", 8, 1, 32)
        error_code = str(result.get("error") or status or "delivery_failed")[:128]
        if attempts >= max_attempts:
            next_state = "exhausted"
            next_attempt = current_time
        else:
            next_state = "retryable_failure"
            base = _int_env("IAT_CHECKOUT_DELIVERY_RETRY_BASE_SECONDS", 30, 5, 3600)
            delay = min(base * (2 ** (attempts - 1)), 3600)
            next_attempt = current_time + delay
        _finish(
            quote_id,
            lease_token,
            state=next_state,
            now=current_time,
            result=result,
            error_code=error_code,
            next_attempt_at=next_attempt,
        )
        if next_state == "exhausted":
            _request_protocol_compensation(quote_id)

    return {**public_delivery_status(quote_id), "payment_verified": True, "claimed": True}


def run_delivery_sweep(*, limit: int = 20) -> dict[str, Any]:
    """Process a bounded batch; safe to run concurrently on several replicas."""
    quote_ids = list_due_deliveries(limit=limit)
    states: dict[str, int] = {}
    for quote_id in quote_ids:
        try:
            result = run_checkout_delivery(quote_id)
            state = str(result.get("state") or "unknown")
        except Exception:
            state = "worker_error"
        states[state] = states.get(state, 0) + 1
    return {"selected": len(quote_ids), "states": states}


def run_settlement_sweep(*, limit: int = 20) -> dict[str, Any]:
    """Retry allocations without ever re-executing the delivered service."""
    init_checkout_delivery_db()
    now = int(time.time())
    safe_limit = max(1, min(int(limit), 100))
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            SELECT quote_id, order_id, result_payload,
                   settlement_attempt_count
            FROM universal_checkout_deliveries
            WHERE state = {p} AND settlement_state = {p}
              AND settlement_next_attempt_at <= {p}
            ORDER BY settlement_next_attempt_at ASC
            LIMIT {p}
            """,
            ("completed", "retryable_failure", now, safe_limit),
        )
        rows = [dict(row) for row in cur.fetchall()]
    finally:
        release_conn(conn)

    completed = 0
    failed = 0
    for row in rows:
        order = get_order_db(row["order_id"])
        try:
            result = json.loads(row.get("result_payload") or "{}")
            from iat.checkout_settlement import allocate_checkout_settlement

            allocation = allocate_checkout_settlement(order or {}, result)
            state = "completed"
            error = None
            completed += 1
        except Exception:
            allocation = {"status": "allocation_error", "retryable": True}
            state = "retryable_failure"
            error = "settlement_allocation_error"
            failed += 1
        attempts = int(row.get("settlement_attempt_count") or 0) + 1
        delay = min(30 * (2 ** max(attempts - 1, 0)), 3600)
        conn = get_conn()
        try:
            cur = conn.cursor()
            p = qmark()
            cur.execute(
                f"""
                UPDATE universal_checkout_deliveries
                SET settlement_state = {p},
                    settlement_attempt_count = {p},
                    settlement_next_attempt_at = {p},
                    settlement_error = {p}, updated_at = {p}
                WHERE quote_id = {p} AND state = {p}
                  AND settlement_state = {p}
                """,
                (
                    state,
                    attempts,
                    None if state == "completed" else now + delay,
                    error,
                    now,
                    row["quote_id"],
                    "completed",
                    "retryable_failure",
                ),
            )
            conn.commit()
        finally:
            release_conn(conn)
        if isinstance(result, dict):
            result["settlement"] = allocation
            conn = get_conn()
            try:
                cur = conn.cursor()
                p = qmark()
                cur.execute(
                    f"""
                    UPDATE universal_checkout_deliveries
                    SET result_payload = {p}
                    WHERE quote_id = {p}
                    """,
                    (json.dumps(result, sort_keys=True), row["quote_id"]),
                )
                conn.commit()
            finally:
                release_conn(conn)
    return {"selected": len(rows), "completed": completed, "failed": failed}


def _delivery_worker_loop() -> None:
    interval = _int_env("IAT_CHECKOUT_DELIVERY_POLL_SECONDS", 10, 2, 300)
    batch = _int_env("IAT_CHECKOUT_DELIVERY_BATCH_SIZE", 20, 1, 100)
    while True:
        try:
            run_delivery_sweep(limit=batch)
            run_settlement_sweep(limit=batch)
        except Exception:
            # The loop is self-healing; individual attempts are persisted.
            pass
        time.sleep(interval)


def start_checkout_delivery_worker() -> bool:
    """Start one in-process poller. Database leases coordinate replicas."""
    global _WORKER_STARTED
    enabled = os.getenv(
        "IAT_CHECKOUT_DELIVERY_WORKER_ENABLED", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return False
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return False
        thread = threading.Thread(
            target=_delivery_worker_loop,
            daemon=True,
            name="iat-checkout-delivery",
        )
        thread.start()
        _WORKER_STARTED = True
        return True
