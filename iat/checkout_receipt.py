"""Buyer-facing final-delivery receipts and conflict-safe acknowledgements."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from solders.keypair import Keypair

from iat.api import db as database
from iat.api.db import get_conn, qmark, release_conn
from iat.security.network import UnsafeNetworkTarget, validate_public_runtime_url


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
                dispatch_attempt_count INTEGER NOT NULL DEFAULT 0,
                dispatch_next_attempt_at INTEGER,
                dispatch_last_error TEXT,
                dispatch_response_code INTEGER,
                dispatch_signature TEXT,
                dispatch_signer TEXT,
                updated_at INTEGER NOT NULL
            )
            """
        )
        columns = {
            "dispatch_attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "dispatch_next_attempt_at": "INTEGER",
            "dispatch_last_error": "TEXT",
            "dispatch_response_code": "INTEGER",
            "dispatch_signature": "TEXT",
            "dispatch_signer": "TEXT",
        }
        for column, definition in columns.items():
            try:
                if database.USE_POSTGRES:
                    conn.cursor().execute(
                        f"ALTER TABLE universal_checkout_delivery_receipts "
                        f"ADD COLUMN IF NOT EXISTS {column} {definition}"
                    )
                else:
                    conn.cursor().execute(
                        f"ALTER TABLE universal_checkout_delivery_receipts "
                        f"ADD COLUMN {column} {definition}"
                    )
            except Exception:
                pass
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
        rebound = False
        if not existing:
            cur.execute(
                f"SELECT * FROM universal_checkout_delivery_receipts WHERE order_id={p}",
                (order_id,),
            )
            order_receipt = cur.fetchone()
            if order_receipt:
                current = dict(order_receipt)
                if current["state"] != "configured" or current.get("payload_digest"):
                    raise DeliveryReceiptError("delivery_order_already_bound")
                cur.execute(
                    f"""UPDATE universal_checkout_delivery_receipts
                    SET quote_id={p}, channel={p}, destination={p}, updated_at={p}
                    WHERE order_id={p} AND quote_id={p} AND state={p}
                      AND payload_digest IS NULL""",
                    (
                        quote_id,
                        channel,
                        clean_destination,
                        current_time,
                        order_id,
                        current["quote_id"],
                        "configured",
                    ),
                )
                if cur.rowcount != 1:
                    raise DeliveryReceiptError("delivery_quote_rebind_conflict")
                existing = order_receipt
                rebound = True
        if existing:
            current = dict(existing)
            if not rebound and current["state"] not in {"configured", "payload_ready"}:
                raise DeliveryReceiptError("delivery_destination_locked")
            if not rebound:
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
            event_type=(
                "delivery_quote_rebound" if rebound else "delivery_destination_configured"
            ),
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


def get_delivery_receipt_by_token(receipt_token: str) -> dict[str, Any] | None:
    if not str(receipt_token or "").startswith("cdr_") or len(receipt_token) > 128:
        return None
    init_delivery_receipt_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM universal_checkout_delivery_receipts WHERE receipt_token={p}",
            (receipt_token,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        release_conn(conn)


def get_delivery_receipt_by_order(order_id: str) -> dict[str, Any] | None:
    init_delivery_receipt_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM universal_checkout_delivery_receipts WHERE order_id={p}",
            (order_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        release_conn(conn)


def settlement_release_receipt_gate(order_id: str) -> dict[str, Any]:
    """Require buyer acceptance for new receipt-enabled checkout deliveries."""
    receipt = get_delivery_receipt_by_order(order_id)
    if not receipt:
        return {
            "release_allowed": True,
            "reason": "legacy_order_without_final_receipt",
            "legacy_compatibility": True,
        }
    state = str(receipt["state"])
    if state == "accepted":
        return {
            "release_allowed": True,
            "reason": "buyer_accepted_sealed_delivery",
            "receipt_state": state,
            "payload_digest": receipt.get("payload_digest"),
        }
    reason = {
        "disputed": "buyer_delivery_dispute_open",
        "delivered": "buyer_delivery_confirmation_pending",
        "dispatch_failed": "final_delivery_dispatch_failed",
        "pending_dispatch": "final_delivery_dispatch_pending",
        "configured": "service_delivery_not_ready",
    }.get(state, "final_delivery_not_accepted")
    return {
        "release_allowed": False,
        "reason": reason,
        "receipt_state": state,
        "payload_digest": receipt.get("payload_digest"),
    }


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
    decided = {**public_delivery_receipt(get_delivery_receipt(quote_id)), "idempotent": False}
    if decision == "disputed":
        try:
            from iat.checkout_compensation import request_compensation

            compensation = request_compensation(
                quote_id,
                requested_by="authenticated_buyer_delivery_dispute",
                now=current_time,
            )
            decided["compensation_state"] = compensation.get("state")
        except Exception:
            decided["compensation_state"] = "review_request_pending"
    return decided


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


def _delivery_keypair() -> Keypair:
    path = os.getenv("IAT_DELIVERY_SIGNING_KEYPAIR_PATH", "").strip()
    if not path:
        raise DeliveryReceiptError("delivery_signing_keypair_not_configured")
    try:
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        raw = bytes(values)
        if len(raw) != 64:
            raise ValueError("invalid_keypair_length")
        return Keypair.from_bytes(raw)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DeliveryReceiptError("delivery_signing_keypair_unavailable") from exc


def _dispatch_backoff(attempt: int) -> int:
    return min(30 * (2 ** max(0, attempt - 1)), 3_600)


def list_due_receipt_dispatches(*, now: int | None = None, limit: int = 20) -> list[str]:
    init_delivery_receipt_db()
    current_time = _now() if now is None else int(now)
    safe_limit = max(1, min(int(limit), 100))
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"""SELECT quote_id FROM universal_checkout_delivery_receipts
            WHERE state={p} AND channel IN ({p}, {p})
              AND (dispatch_next_attempt_at IS NULL OR dispatch_next_attempt_at<={p})
            ORDER BY payload_ready_at ASC LIMIT {safe_limit}""",
            ("pending_dispatch", "webhook", "email", current_time),
        )
        return [str(row["quote_id"]) for row in cur.fetchall()]
    finally:
        release_conn(conn)


def dispatch_webhook(
    quote_id: str,
    *,
    now: int | None = None,
    post: Any = requests.post,
) -> dict[str, Any]:
    receipt = get_delivery_receipt(quote_id)
    if not receipt:
        raise DeliveryReceiptError("delivery_receipt_not_found")
    if receipt["channel"] != "webhook":
        raise DeliveryReceiptError("delivery_channel_is_not_webhook")
    if receipt["state"] == "delivered":
        return {**public_delivery_receipt(receipt), "idempotent": True}
    if receipt["state"] != "pending_dispatch":
        raise DeliveryReceiptError("delivery_not_ready_for_dispatch")
    current_time = _now() if now is None else int(now)
    if receipt.get("dispatch_next_attempt_at") and int(receipt["dispatch_next_attempt_at"]) > current_time:
        return {**public_delivery_receipt(receipt), "retry_wait": True}

    from iat.checkout_delivery import get_delivery

    delivery = get_delivery(quote_id)
    result = (delivery or {}).get("result")
    if not isinstance(result, dict) or _digest(result) != receipt["payload_digest"]:
        raise DeliveryReceiptError("sealed_delivery_payload_unavailable")
    try:
        validate_public_runtime_url(receipt["destination"])
    except UnsafeNetworkTarget as exc:
        raise DeliveryReceiptError(str(exc)) from exc
    keypair = _delivery_keypair()
    body = {
        "schema_version": "2026-08-01",
        "event": "iat.delivery.completed",
        "quote_id": quote_id,
        "order_id": receipt["order_id"],
        "receipt_id": receipt["receipt_token"],
        "payload_digest": receipt["payload_digest"],
        "payload_ready_at": int(receipt["payload_ready_at"]),
        "result": result,
    }
    body_bytes = _canonical_payload(body).encode()
    signature = str(keypair.sign_message(body_bytes))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "IAT-Delivery/1.0",
        "Idempotency-Key": receipt["receipt_token"],
        "X-IAT-Delivery-Signature": signature,
        "X-IAT-Delivery-Signer": str(keypair.pubkey()),
        "X-IAT-Delivery-Timestamp": str(current_time),
    }
    response_code = None
    error = None
    try:
        response = post(
            receipt["destination"],
            data=body_bytes,
            headers=headers,
            timeout=(3.05, 15),
            allow_redirects=False,
        )
        response_code = int(response.status_code)
        delivered = 200 <= response_code < 300
        if not delivered:
            error = f"webhook_http_{response_code}"
    except requests.RequestException as exc:
        delivered = False
        error = f"webhook_{type(exc).__name__.lower()}"

    attempt = int(receipt.get("dispatch_attempt_count") or 0) + 1
    try:
        configured_max_attempts = int(
            os.getenv("IAT_DELIVERY_DISPATCH_MAX_ATTEMPTS", "8")
        )
    except ValueError:
        configured_max_attempts = 8
    max_attempts = max(1, min(configured_max_attempts, 20))
    state = "delivered" if delivered else ("dispatch_failed" if attempt >= max_attempts else "pending_dispatch")
    next_attempt = None if delivered or state == "dispatch_failed" else current_time + _dispatch_backoff(attempt)
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE universal_checkout_delivery_receipts
            SET state={p}, dispatch_attempt_count={p}, dispatch_next_attempt_at={p},
                dispatch_last_error={p}, dispatch_response_code={p},
                dispatch_signature={p}, dispatch_signer={p}, dispatched_at={p}, updated_at={p}
            WHERE quote_id={p} AND state={p}""",
            (
                state,
                attempt,
                next_attempt,
                error,
                response_code,
                signature,
                str(keypair.pubkey()),
                current_time if delivered else None,
                current_time,
                quote_id,
                "pending_dispatch",
            ),
        )
        if cur.rowcount != 1:
            raise DeliveryReceiptError("delivery_dispatch_conflict")
        _insert_event(
            cur,
            quote_id=quote_id,
            event_type="delivery_webhook_dispatched" if delivered else "delivery_webhook_failed",
            state=state,
            payload_digest=receipt["payload_digest"],
            actor="delivery_dispatcher",
            now=current_time,
        )
        conn.commit()
    finally:
        release_conn(conn)
    return {**public_delivery_receipt(get_delivery_receipt(quote_id)), "idempotent": False}


def _send_smtp(message: EmailMessage) -> None:
    host = os.getenv("IAT_DELIVERY_SMTP_HOST", "").strip()
    from_address = os.getenv("IAT_DELIVERY_EMAIL_FROM", "").strip()
    if not host or not from_address:
        raise DeliveryReceiptError("delivery_smtp_not_configured")
    try:
        port = int(os.getenv("IAT_DELIVERY_SMTP_PORT", "587"))
    except ValueError as exc:
        raise DeliveryReceiptError("delivery_smtp_port_invalid") from exc
    username = os.getenv("IAT_DELIVERY_SMTP_USERNAME", "").strip()
    password = os.getenv("IAT_DELIVERY_SMTP_PASSWORD", "")
    use_ssl = os.getenv("IAT_DELIVERY_SMTP_SSL", "false").lower() == "true"
    require_starttls = os.getenv("IAT_DELIVERY_SMTP_STARTTLS", "true").lower() != "false"
    context = ssl.create_default_context()
    try:
        client = (
            smtplib.SMTP_SSL(host, port, timeout=20, context=context)
            if use_ssl
            else smtplib.SMTP(host, port, timeout=20)
        )
        with client:
            if not use_ssl and require_starttls:
                client.starttls(context=context)
            if username:
                if not password:
                    raise DeliveryReceiptError("delivery_smtp_password_required")
                client.login(username, password)
            client.send_message(message, from_addr=from_address)
    except DeliveryReceiptError:
        raise
    except (OSError, smtplib.SMTPException) as exc:
        raise DeliveryReceiptError(f"delivery_smtp_{type(exc).__name__.lower()}") from exc


def dispatch_email(
    quote_id: str,
    *,
    now: int | None = None,
    send: Any = _send_smtp,
) -> dict[str, Any]:
    receipt = get_delivery_receipt(quote_id)
    if not receipt:
        raise DeliveryReceiptError("delivery_receipt_not_found")
    if receipt["channel"] != "email":
        raise DeliveryReceiptError("delivery_channel_is_not_email")
    if receipt["state"] == "delivered":
        return {**public_delivery_receipt(receipt), "idempotent": True}
    if receipt["state"] != "pending_dispatch":
        raise DeliveryReceiptError("delivery_not_ready_for_dispatch")
    current_time = _now() if now is None else int(now)
    if receipt.get("dispatch_next_attempt_at") and int(receipt["dispatch_next_attempt_at"]) > current_time:
        return {**public_delivery_receipt(receipt), "retry_wait": True}

    from iat.checkout_delivery import get_delivery

    result = (get_delivery(quote_id) or {}).get("result")
    if not isinstance(result, dict) or _digest(result) != receipt["payload_digest"]:
        raise DeliveryReceiptError("sealed_delivery_payload_unavailable")
    canonical_result = _canonical_payload(result)
    if len(canonical_result.encode()) > 250_000:
        raise DeliveryReceiptError("delivery_email_payload_too_large")
    keypair = _delivery_keypair()
    signature = str(keypair.sign_message(canonical_result.encode()))
    public_site = os.getenv(
        "IAT_PUBLIC_SITE_URL", "https://iat-protocol.pages.dev"
    ).strip().rstrip("/")
    decision_url = f"{public_site}/delivery/#receipt={receipt['receipt_token']}"
    from_address = os.getenv("IAT_DELIVERY_EMAIL_FROM", "IAT Delivery <delivery@iat.invalid>")
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = receipt["destination"]
    message["Subject"] = f"IAT delivery ready — {quote_id}"
    message["Message-ID"] = f"<{receipt['receipt_token']}@delivery.iatprotocol>"
    message["X-IAT-Receipt-ID"] = receipt["receipt_token"]
    message["X-IAT-Payload-Digest"] = receipt["payload_digest"]
    message["X-IAT-Delivery-Signature"] = signature
    message["X-IAT-Delivery-Signer"] = str(keypair.pubkey())
    message.set_content(
        "Your IAT service result is ready.\n\n"
        f"Quote: {quote_id}\n"
        f"Receipt: {receipt['receipt_token']}\n"
        f"Payload SHA-256: {receipt['payload_digest']}\n"
        f"Ed25519 signer: {keypair.pubkey()}\n"
        f"Ed25519 signature: {signature}\n\n"
        "Result (canonical JSON):\n"
        f"{canonical_result}\n\n"
        "Review, accept, or report an issue here:\n"
        f"{decision_url}\n\n"
        "Opening this link does not accept the delivery. A separate explicit decision is required.\n"
    )
    error = None
    try:
        send(message)
        delivered = True
    except DeliveryReceiptError as exc:
        delivered = False
        error = str(exc)[:128]
    except Exception as exc:
        delivered = False
        error = f"delivery_email_{type(exc).__name__.lower()}"[:128]

    attempt = int(receipt.get("dispatch_attempt_count") or 0) + 1
    try:
        configured_max_attempts = int(os.getenv("IAT_DELIVERY_DISPATCH_MAX_ATTEMPTS", "8"))
    except ValueError:
        configured_max_attempts = 8
    max_attempts = max(1, min(configured_max_attempts, 20))
    state = "delivered" if delivered else ("dispatch_failed" if attempt >= max_attempts else "pending_dispatch")
    next_attempt = None if delivered or state == "dispatch_failed" else current_time + _dispatch_backoff(attempt)
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE universal_checkout_delivery_receipts
            SET state={p}, dispatch_attempt_count={p}, dispatch_next_attempt_at={p},
                dispatch_last_error={p}, dispatch_signature={p}, dispatch_signer={p},
                dispatched_at={p}, updated_at={p}
            WHERE quote_id={p} AND state={p}""",
            (
                state,
                attempt,
                next_attempt,
                error,
                signature,
                str(keypair.pubkey()),
                current_time if delivered else None,
                current_time,
                quote_id,
                "pending_dispatch",
            ),
        )
        if cur.rowcount != 1:
            raise DeliveryReceiptError("delivery_dispatch_conflict")
        _insert_event(
            cur,
            quote_id=quote_id,
            event_type="delivery_email_dispatched" if delivered else "delivery_email_failed",
            state=state,
            payload_digest=receipt["payload_digest"],
            actor="delivery_dispatcher",
            now=current_time,
        )
        conn.commit()
    finally:
        release_conn(conn)
    return {**public_delivery_receipt(get_delivery_receipt(quote_id)), "idempotent": False}


def run_receipt_dispatch_sweep(*, limit: int = 20) -> dict[str, int]:
    selected = list_due_receipt_dispatches(limit=limit)
    delivered = failed = 0
    for quote_id in selected:
        try:
            receipt = get_delivery_receipt(quote_id)
            result = (
                dispatch_email(quote_id)
                if receipt and receipt["channel"] == "email"
                else dispatch_webhook(quote_id)
            )
            delivered += int(result.get("state") == "delivered")
            failed += int(result.get("state") != "delivered")
        except DeliveryReceiptError:
            failed += 1
    return {"selected": len(selected), "delivered": delivered, "failed": failed}


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
        "dispatch_attempt_count": int(receipt.get("dispatch_attempt_count") or 0),
        "dispatch_next_attempt_at": receipt.get("dispatch_next_attempt_at"),
        "dispatch_last_error": receipt.get("dispatch_last_error"),
        "dispatch_response_code": receipt.get("dispatch_response_code"),
        "dispatch_signer": receipt.get("dispatch_signer"),
        "buyer_confirmation_required": receipt["state"] == "delivered",
        "available_channels": sorted(CHANNELS),
    }
