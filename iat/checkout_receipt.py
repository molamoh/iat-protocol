"""Buyer-facing final-delivery receipts and conflict-safe acknowledgements."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from typing import Any
from urllib.parse import urlparse

from iat.api import db as database
from iat.api.db import get_conn, qmark, release_conn


CHANNELS = {"api_pull", "email", "webhook"}
DECISIONS = {"accepted", "disputed"}
DISPUTE_CODES = {
    "not_received",
    "incomplete",
    "incorrect",
    "unreadable",
    "other",
}


class DeliveryReceiptError(ValueError):
    pass


def _now() -> int:
    return int(time.time())


def _canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode()).hexdigest()


def _masked_destination(channel: str, destination: str) -> str | None:
    if channel == "api_pull" or not destination:
        return None
    if channel == "email":
        local, _, domain = destination.partition("@")
        return f"{local[:1]}***@{domain}"
    parsed = urlparse(destination)
    return f"https://{parsed.hostname}/…" if parsed.hostname else "https://…"


def validate_destination(channel: str, destination: str | None) -> str:
    channel = str(channel or "").strip().lower()
    value = str(destination or "").strip()
    if channel not in CHANNELS:
        raise DeliveryReceiptError("unsupported_delivery_channel")
    if channel == "api_pull":
        if value:
            raise DeliveryReceiptError("api_pull_destination_must_be_empty")
        return ""
    if channel == "email":
        if len(value) > 320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise DeliveryReceiptError("valid_delivery_email_required")
        return value.lower()
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise DeliveryReceiptError("valid_https_delivery_webhook_required")
    if parsed.fragment or len(value) > 2_000:
        raise DeliveryReceiptError("unsafe_delivery_webhook")
    return value


def init_delivery_receipt_db() -> None:
    conn = get_conn()
    try:
        conn.cursor().execute(
            """
            CREATE TABLE IF NOT EXISTS universal_checkout_delivery_receipts (
                quote_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL UNIQUE,
                channel TEXT NOT NULL,
                destination TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL,
                payload_digest TEXT,
                receipt_token TEXT NOT NULL UNIQUE,
                configured_at INTEGER NOT NULL,
                payload_ready_at INTEGER,
                dispatched_at INTEGER,
                accepted_at INTEGER,
                disputed_at INTEGER,
                dispute_code TEXT,
                buyer_message TEXT,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.cursor().execute(
            """
            CREATE TABLE IF NOT EXISTS universal_checkout_delivery_receipt_events (
                event_id TEXT PRIMARY KEY,
                quote_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                state TEXT NOT NULL,
                payload_digest TEXT,
                actor TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        release_conn(conn)


def _insert_event(
    cur: Any,
    *,
    quote_id: str,
    event_type: str,
    state: str,
    payload_digest: str | None,
    actor: str,
    now: int,
) -> None:
    p = qmark()
    cur.execute(
        f"""INSERT INTO universal_checkout_delivery_receipt_events
        (event_id, quote_id, event_type, state, payload_digest, actor, created_at)
        VALUES ({p},{p},{p},{p},{p},{p},{p})""",
        (
            f"cdre_{secrets.token_hex(16)}",
            quote_id,
            event_type,
            state,
            payload_digest,
            actor[:64],
            now,
        ),
    )


def configure_delivery_receipt(
    *, quote_id: str,
    order_id: str,
    channel: str,
    destination: str | None,
    now: int | None = None,
) -> dict[str, Any]:
    init_delivery_receipt_db()
    clean_destination = validate_destination(channel, destination)
    channel = channel.strip().lower()
    current_time = _now() if now is None else int(now)
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"SELECT * FROM universal_checkout_delivery_receipts WHERE quote_id={p}",
            (quote_id,),
        )
        existing = cur.fetchone()
        if existing:
            current = dict(existing)
            if current["state"] not in {"configured", "payload_ready"}:
                raise DeliveryReceiptError("delivery_destination_locked")
            cur.execute(
                f"""UPDATE universal_checkout_delivery_receipts
                SET channel={p}, destination={p}, updated_at={p}
                WHERE quote_id={p}""",
                (channel, clean_destination, current_time, quote_id),
            )
        else:
            cur.execute(
                f"""INSERT INTO universal_checkout_delivery_receipts
                (quote_id, order_id, channel, destination, state, receipt_token,
                 configured_at, updated_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p})""",
                (
                    quote_id,
                    order_id,
                    channel,
                    clean_destination,
                    "configured",
                    f"cdr_{secrets.token_urlsafe(24)}",
                    current_time,
                    current_time,
                ),
            )
        _insert_event(
            cur,
            quote_id=quote_id,
            event_type="delivery_destination_configured",
            state="configured" if not existing else dict(existing)["state"],
            payload_digest=(dict(existing).get("payload_digest") if existing else None),
            actor="authenticated_buyer",
            now=current_time,
        )
        conn.commit()
    finally:
        release_conn(conn)
    return public_delivery_receipt(get_delivery_receipt(quote_id))


def get_delivery_receipt(quote_id: str) -> dict[str, Any] | None:
    init_delivery_receipt_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM universal_checkout_delivery_receipts WHERE quote_id={p}",
            (quote_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        release_conn(conn)


def publish_delivery_payload(
    *, quote_id: str,
    order_id: str,
    payload: dict[str, Any],
    now: int | None = None,
) -> dict[str, Any]:
    """Seal the final result; API-pull is delivered immediately, others await dispatch."""
    receipt = get_delivery_receipt(quote_id)
    if not receipt:
        configure_delivery_receipt(
            quote_id=quote_id,
            order_id=order_id,
            channel="api_pull",
            destination=None,
            now=now,
        )
        receipt = get_delivery_receipt(quote_id)
    assert receipt is not None
    payload_digest = _digest(payload)
    if receipt.get("payload_digest"):
        if not secrets.compare_digest(str(receipt["payload_digest"]), payload_digest):
            raise DeliveryReceiptError("delivery_payload_digest_conflict")
        return public_delivery_receipt(receipt)
    current_time = _now() if now is None else int(now)
    state = "delivered" if receipt["channel"] == "api_pull" else "pending_dispatch"
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE universal_checkout_delivery_receipts
            SET state={p}, payload_digest={p}, payload_ready_at={p},
                dispatched_at={p}, updated_at={p}
            WHERE quote_id={p} AND payload_digest IS NULL""",
            (
                state,
                payload_digest,
                current_time,
                current_time if state == "delivered" else None,
                current_time,
                quote_id,
            ),
        )
        if cur.rowcount != 1:
            raise DeliveryReceiptError("delivery_payload_publish_conflict")
        _insert_event(
            cur,
            quote_id=quote_id,
            event_type="delivery_payload_sealed",
            state=state,
            payload_digest=payload_digest,
            actor="protocol",
            now=current_time,
        )
        conn.commit()
    finally:
        release_conn(conn)
    return public_delivery_receipt(get_delivery_receipt(quote_id))


def acknowledge_delivery(
    *,
    quote_id: str,
    decision: str,
    dispute_code: str | None = None,
    message: str = "",
    now: int | None = None,
) -> dict[str, Any]:
    receipt = get_delivery_receipt(quote_id)
    if not receipt:
        raise DeliveryReceiptError("delivery_receipt_not_found")
    decision = str(decision or "").lower()
    if decision not in DECISIONS:
        raise DeliveryReceiptError("invalid_delivery_decision")
    if receipt["state"] in DECISIONS:
        if receipt["state"] == decision:
            return {**public_delivery_receipt(receipt), "idempotent": True}
        raise DeliveryReceiptError("delivery_decision_already_final")
    if receipt["state"] != "delivered":
        raise DeliveryReceiptError("delivery_not_yet_dispatched")
    clean_message = str(message or "").strip()[:2_000]
    if decision == "disputed":
        if dispute_code not in DISPUTE_CODES:
            raise DeliveryReceiptError("valid_dispute_code_required")
        if len(clean_message) < 10:
            raise DeliveryReceiptError("dispute_explanation_required")
    else:
        dispute_code = None
        clean_message = ""
    current_time = _now() if now is None else int(now)
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE universal_checkout_delivery_receipts
            SET state={p}, accepted_at={p}, disputed_at={p}, dispute_code={p},
                buyer_message={p}, updated_at={p}
            WHERE quote_id={p} AND state={p}""",
            (
                decision,
                current_time if decision == "accepted" else None,
                current_time if decision == "disputed" else None,
                dispute_code,
                clean_message or None,
                current_time,
                quote_id,
                "delivered",
            ),
        )
        if cur.rowcount != 1:
            raise DeliveryReceiptError("delivery_decision_conflict")
        _insert_event(
            cur,
            quote_id=quote_id,
            event_type=f"delivery_{decision}",
            state=decision,
            payload_digest=receipt.get("payload_digest"),
            actor="authenticated_buyer",
            now=current_time,
        )
        conn.commit()
    finally:
        release_conn(conn)
    return {**public_delivery_receipt(get_delivery_receipt(quote_id)), "idempotent": False}


def delivery_receipt_events(quote_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    init_delivery_receipt_db()
    conn = get_conn()
    try:
        p = qmark()
        safe_limit = max(1, min(int(limit), 500))
        cur = conn.cursor()
        cur.execute(
            f"""SELECT event_id, event_type, state, payload_digest, actor, created_at
            FROM universal_checkout_delivery_receipt_events
            WHERE quote_id={p} ORDER BY created_at ASC LIMIT {safe_limit}""",
            (quote_id,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        release_conn(conn)


def public_delivery_receipt(receipt: dict[str, Any] | None) -> dict[str, Any]:
    if not receipt:
        return {"state": "not_configured", "available_channels": sorted(CHANNELS)}
    return {
        "state": receipt["state"],
        "channel": receipt["channel"],
        "destination": _masked_destination(receipt["channel"], receipt["destination"]),
        "payload_digest": receipt.get("payload_digest"),
        "receipt_token": receipt["receipt_token"],
        "configured_at": receipt["configured_at"],
        "payload_ready_at": receipt.get("payload_ready_at"),
        "dispatched_at": receipt.get("dispatched_at"),
        "accepted_at": receipt.get("accepted_at"),
        "disputed_at": receipt.get("disputed_at"),
        "dispute_code": receipt.get("dispute_code"),
        "buyer_confirmation_required": receipt["state"] == "delivered",
        "available_channels": sorted(CHANNELS),
    }
