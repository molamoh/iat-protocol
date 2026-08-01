"""Governed compensation state machine for paid but undelivered checkouts."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from iat.api.db import get_conn, qmark, release_conn
from iat.config import IAT_TOKEN_ADDRESS


ELIGIBLE_DELIVERY_STATES = {"exhausted", "blocked"}
TERMINAL_STATES = {"denied", "confirmed"}


def init_compensation_db() -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS universal_checkout_compensations (
                compensation_id TEXT PRIMARY KEY,
                quote_id TEXT NOT NULL UNIQUE,
                order_id TEXT NOT NULL UNIQUE,
                buyer_wallet TEXT NOT NULL,
                route TEXT NOT NULL,
                refund_asset TEXT NOT NULL,
                refund_mint TEXT NOT NULL,
                refund_amount_minor TEXT NOT NULL,
                state TEXT NOT NULL,
                eligibility_reason TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                decision_reason TEXT,
                decision_actor TEXT,
                payout_signature TEXT UNIQUE,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                decided_at INTEGER,
                confirmed_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS universal_checkout_compensation_events (
                event_id TEXT PRIMARY KEY,
                compensation_id TEXT NOT NULL,
                quote_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT NOT NULL,
                actor TEXT NOT NULL,
                reason TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        release_conn(conn)


def _event(
    cur: Any,
    *,
    compensation_id: str,
    quote_id: str,
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
        INSERT INTO universal_checkout_compensation_events (
            event_id, compensation_id, quote_id, event_type, from_state,
            to_state, actor, reason, created_at
        ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """,
        (
            f"cce_{secrets.token_hex(16)}",
            compensation_id,
            quote_id,
            event_type,
            from_state,
            to_state,
            actor[:128],
            reason,
            now,
        ),
    )


def get_compensation(quote_id: str) -> dict[str, Any] | None:
    init_compensation_db()
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            SELECT * FROM universal_checkout_compensations
            WHERE quote_id = {p}
            """,
            (quote_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        release_conn(conn)


def _refund_terms(quote: dict[str, Any]) -> tuple[str, str, str]:
    payload = json.loads(quote["quote_payload"])
    if quote["route"] == "treasury":
        return (
            str(payload["input"]["asset"]),
            str(payload["input"]["mint"]),
            str(payload["input"]["amount_minor"]),
        )
    return (
        "IAT",
        IAT_TOKEN_ADDRESS,
        str(payload["output"]["amount_minor"]),
    )


def request_compensation(
    quote_id: str,
    *,
    requested_by: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Create an idempotent review request only for terminal non-delivery."""
    init_compensation_db()
    current_time = int(time.time()) if now is None else int(now)
    existing = get_compensation(quote_id)
    if existing:
        return {**existing, "idempotent": True}

    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            SELECT q.*, d.state AS delivery_state,
                   r.state AS final_receipt_state
            FROM universal_checkout_quotes q
            JOIN universal_checkout_deliveries d ON d.quote_id = q.quote_id
            LEFT JOIN universal_checkout_delivery_receipts r ON r.quote_id = q.quote_id
            WHERE q.quote_id = {p}
            """,
            (quote_id,),
        )
        joined = cur.fetchone()
        if not joined:
            raise ValueError("checkout_delivery_not_found")
        quote = dict(joined)
        if str(quote.get("state")) != "confirmed":
            raise ValueError("payment_not_confirmed")
        delivery_state = str(quote["delivery_state"])
        final_receipt_state = str(quote.get("final_receipt_state") or "")
        buyer_disputed = final_receipt_state == "disputed"
        if delivery_state not in ELIGIBLE_DELIVERY_STATES and not buyer_disputed:
            raise ValueError("compensation_not_eligible")
        asset, mint, amount_minor = _refund_terms(quote)
        compensation_id = f"cmp_{secrets.token_hex(16)}"
        if buyer_disputed:
            reason = "buyer_disputed_sealed_delivery"
        elif delivery_state == "exhausted":
            reason = "delivery_attempts_exhausted"
        else:
            reason = "foundation_delivery_blocked"
        cur.execute(
            f"""
            INSERT INTO universal_checkout_compensations (
                compensation_id, quote_id, order_id, buyer_wallet, route,
                refund_asset, refund_mint, refund_amount_minor, state,
                eligibility_reason, requested_by, created_at, updated_at
            ) VALUES (
                {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
            )
            """,
            (
                compensation_id,
                quote_id,
                quote["order_id"],
                quote["buyer_wallet"],
                quote["route"],
                asset,
                mint,
                amount_minor,
                "pending_review",
                reason,
                requested_by[:128],
                current_time,
                current_time,
            ),
        )
        _event(
            cur,
            compensation_id=compensation_id,
            quote_id=quote_id,
            event_type="compensation_requested",
            from_state=None,
            to_state="pending_review",
            actor=requested_by,
            reason=reason,
            now=current_time,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        existing = get_compensation(quote_id)
        if existing:
            return {**existing, "idempotent": True}
        raise
    finally:
        release_conn(conn)
    created = get_compensation(quote_id)
    return {**(created or {}), "idempotent": False}


def decide_compensation(
    quote_id: str,
    *,
    approve: bool,
    reason: str,
    actor: str = "admin_api_key",
    now: int | None = None,
) -> dict[str, Any]:
    clean_reason = " ".join(str(reason or "").split())
    if not 8 <= len(clean_reason) <= 500:
        raise ValueError("compensation_decision_reason_invalid")
    current_time = int(time.time()) if now is None else int(now)
    target = "approved" if approve else "denied"
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            SELECT * FROM universal_checkout_compensations
            WHERE quote_id = {p}
            """,
            (quote_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("compensation_not_found")
        current = dict(row)
        if current["state"] == target:
            return {**current, "idempotent": True}
        if current["state"] != "pending_review":
            raise ValueError("compensation_decision_not_allowed")
        cur.execute(
            f"""
            UPDATE universal_checkout_compensations
            SET state = {p}, decision_reason = {p}, decision_actor = {p},
                decided_at = {p}, updated_at = {p}
            WHERE quote_id = {p} AND state = {p}
            """,
            (
                target,
                clean_reason,
                actor[:128],
                current_time,
                current_time,
                quote_id,
                "pending_review",
            ),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise ValueError("compensation_decision_conflict")
        _event(
            cur,
            compensation_id=current["compensation_id"],
            quote_id=quote_id,
            event_type="compensation_decided",
            from_state="pending_review",
            to_state=target,
            actor=actor,
            reason=clean_reason,
            now=current_time,
        )
        conn.commit()
    finally:
        release_conn(conn)
    decided = get_compensation(quote_id)
    return {**(decided or {}), "idempotent": False}


def compensation_dashboard(*, limit: int = 100) -> dict[str, Any]:
    init_compensation_db()
    safe_limit = max(1, min(int(limit), 500))
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT state, COUNT(*) AS count
            FROM universal_checkout_compensations
            GROUP BY state
            """
        )
        counts = {
            str(dict(row)["state"]): int(dict(row)["count"])
            for row in cur.fetchall()
        }
        p = qmark()
        cur.execute(
            f"""
            SELECT compensation_id, quote_id, order_id, route, refund_asset,
                   refund_mint, refund_amount_minor, state,
                   eligibility_reason, requested_by, decision_reason,
                   decision_actor, created_at, updated_at, decided_at,
                   confirmed_at
            FROM universal_checkout_compensations
            ORDER BY
                CASE WHEN state = {p} THEN 0 ELSE 1 END,
                updated_at ASC
            LIMIT {p}
            """,
            ("pending_review", safe_limit),
        )
        return {
            "status": "ok",
            "state_counts": counts,
            "total": sum(counts.values()),
            "items": [dict(row) for row in cur.fetchall()],
        }
    finally:
        release_conn(conn)


def public_compensation(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not value:
        return None
    return {
        key: value.get(key)
        for key in (
            "compensation_id",
            "state",
            "refund_asset",
            "refund_mint",
            "refund_amount_minor",
            "eligibility_reason",
            "created_at",
            "updated_at",
            "decided_at",
            "confirmed_at",
        )
    }
