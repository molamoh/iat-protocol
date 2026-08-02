"""Public universal-checkout API with fail-closed configuration."""

from __future__ import annotations

import base64
import json
import hashlib
import hmac
import os
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal, ROUND_UP
from typing import Any

import requests
from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, Field
from solders.pubkey import Pubkey
from solders.signature import Signature
from spl.token.instructions import get_associated_token_address

from iat.checkout import (
    AssetSnapshot,
    CheckoutPolicy,
    CheckoutRejected,
    RaydiumSnapshot,
    canonical_hash,
    decimal_value,
    quote_hybrid_checkout,
)
from iat.checkout_solana import (
    SPL_TOKEN_PROGRAM_ID,
    SolanaPlanError,
    build_direct_usdc_purchase_plan,
)
from iat.config import IAT_DECIMALS, IAT_TOKEN_ADDRESS
from iat.raydium import (
    RaydiumClient,
    RaydiumError,
    RaydiumPolicy,
)
from iat.checkout_verifier import (
    CheckoutVerificationError,
    SolanaCheckoutVerifier,
    message_hash_from_transaction_base64,
)
from iat.quote_signer import QuoteSigningRejected, verify_quote_authorization
from iat.api.db import get_conn, get_order_db, qmark, release_conn
from iat.api import db as database
from iat.checkout_delivery import (
    accelerate_foundation_retry,
    enqueue_delivery_tx,
    get_delivery,
    init_checkout_delivery_db,
    public_delivery_status,
    resume_review_required_delivery,
    run_checkout_delivery,
)
from iat.checkout_compensation import (
    get_compensation,
    init_compensation_db,
    public_compensation,
    request_compensation,
)
from iat.checkout_receipt import (
    DeliveryReceiptError,
    acknowledge_delivery,
    configure_delivery_receipt,
    get_delivery_receipt,
    get_delivery_receipt_by_token,
    init_delivery_receipt_db,
    list_buyer_delivery_receipts,
    open_delivery_inbox,
    public_delivery_receipt,
    publish_delivery_payload,
    record_email_provider_event,
)


router = APIRouter(prefix="/payments/v1/universal", tags=["universal-checkout"])
ACTIVE_STATES = ("quoted", "prepared", "submitted")
QUOTE_SIGNER_MAX_LIFETIME_SECONDS = 120
DEVNET_CIRCLE_USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
DEVNET_FIXED_USDC_ORACLE = "circle_devnet_smoke"
_LOCAL_RESERVATION_LOCK = threading.RLock()
_POSTGRES_RESERVATION_LOCK_ID = 4_280_024_071


class UniversalQuoteRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=128)
    buyer_wallet: str = Field(min_length=32, max_length=64)
    buyer_secret: str = Field(min_length=16, max_length=256)
    input_asset: str = Field(min_length=2, max_length=16)


class UniversalPrepareRequest(BaseModel):
    buyer_wallet: str = Field(min_length=32, max_length=64)
    buyer_secret: str = Field(min_length=16, max_length=256)


class UniversalSubmitRequest(UniversalPrepareRequest):
    tx_signature: str = Field(min_length=64, max_length=128)


class UniversalAuthorizeRequest(UniversalPrepareRequest):
    transaction_base64: str = Field(min_length=64, max_length=20_000)


class UniversalDeliveryDestinationRequest(UniversalPrepareRequest):
    channel: str = Field(min_length=5, max_length=16)
    destination: str | None = Field(default=None, max_length=2_000)


class UniversalDeliveryDecisionRequest(UniversalPrepareRequest):
    decision: str = Field(min_length=8, max_length=16)
    dispute_code: str | None = Field(default=None, max_length=32)
    message: str = Field(default="", max_length=2_000)


class PublicDeliveryDecisionRequest(BaseModel):
    decision: str = Field(min_length=8, max_length=16)
    dispute_code: str | None = Field(default=None, max_length=32)
    message: str = Field(default="", max_length=2_000)


def _encode_inbox_cursor(configured_at: int, quote_id: str) -> str:
    raw = json.dumps(
        {"configured_at": int(configured_at), "quote_id": str(quote_id)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_inbox_cursor(cursor: str | None) -> tuple[int | None, str]:
    if not cursor:
        return None, ""
    if len(cursor) > 512:
        raise HTTPException(status_code=422, detail="invalid_inbox_cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        configured_at = int(value["configured_at"])
        quote_id = str(value["quote_id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="invalid_inbox_cursor") from exc
    if configured_at <= 0 or not quote_id or len(quote_id) > 128:
        raise HTTPException(status_code=422, detail="invalid_inbox_cursor")
    return configured_at, quote_id


def _authorize_mailjet_event(authorization: str | None) -> None:
    expected_password = os.getenv("IAT_MAILJET_EVENT_SECRET", "")
    expected_username = os.getenv(
        "IAT_MAILJET_EVENT_USERNAME", "iat-mailjet"
    ).strip()
    if not expected_password or not expected_username:
        raise HTTPException(status_code=503, detail="mailjet_event_auth_not_configured")
    scheme, _, encoded = str(authorization or "").partition(" ")
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        username, separator, password = decoded.partition(":")
    except (ValueError, UnicodeDecodeError):
        username = password = separator = ""
    authorized = (
        scheme.lower() == "basic"
        and separator == ":"
        and hmac.compare_digest(username, expected_username)
        and hmac.compare_digest(password, expected_password)
    )
    if not authorized:
        raise HTTPException(
            status_code=401,
            detail="invalid_mailjet_event_credential",
            headers={"WWW-Authenticate": 'Basic realm="iat-mailjet-events"'},
        )


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _quote_signer_compatible_policy(policy: CheckoutPolicy) -> CheckoutPolicy:
    if not _bool_env("IAT_QUOTE_SIGNER_CLIENT_ENABLED"):
        return policy
    return replace(
        policy,
        quote_ttl_seconds=min(
            policy.quote_ttl_seconds,
            QUOTE_SIGNER_MAX_LIFETIME_SECONDS,
        ),
    )


def _decimal_env(name: str, default: str) -> Decimal:
    return decimal_value(os.getenv(name, default), name.lower())


def _json_env(name: str) -> dict[str, Any]:
    raw = os.getenv(name, "{}").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        raw = raw[1:-1]
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CheckoutRejected(f"invalid_{name.lower()}") from exc
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CheckoutRejected(f"invalid_{name.lower()}") from exc
    if not isinstance(value, dict):
        raise CheckoutRejected(f"invalid_{name.lower()}")
    return value


def load_checkout_policy() -> CheckoutPolicy:
    pools = tuple(
        item.strip()
        for item in os.getenv("IAT_RAYDIUM_ALLOWED_POOLS", "").split(",")
        if item.strip()
    )
    return CheckoutPolicy(
        treasury_enabled=_bool_env("IAT_TREASURY_CHECKOUT_ENABLED"),
        raydium_enabled=_bool_env("IAT_RAYDIUM_CHECKOUT_ENABLED"),
        quote_ttl_seconds=int(os.getenv("IAT_CHECKOUT_QUOTE_TTL_SECONDS", "60")),
        oracle_max_age_seconds=int(os.getenv("IAT_CHECKOUT_ORACLE_MAX_AGE_SECONDS", "90")),
        treasury_spread_bps=int(os.getenv("IAT_TREASURY_SPREAD_BPS", "50")),
        max_order_iat=_decimal_env("IAT_CHECKOUT_MAX_ORDER_IAT", "100"),
        wallet_daily_iat_cap=_decimal_env("IAT_CHECKOUT_WALLET_DAILY_IAT_CAP", "250"),
        treasury_daily_iat_cap=_decimal_env("IAT_TREASURY_DAILY_IAT_CAP", "1000"),
        treasury_inventory_iat=_decimal_env("IAT_TREASURY_INVENTORY_IAT", "0"),
        iat_usd_reference_price=_decimal_env("IAT_REFERENCE_PRICE_USD", "0"),
        max_raydium_price_impact_bps=int(
            os.getenv("IAT_RAYDIUM_MAX_PRICE_IMPACT_BPS", "300")
        ),
        min_raydium_liquidity_usd=_decimal_env(
            "IAT_RAYDIUM_MIN_LIQUIDITY_USD", "10000"
        ),
        max_reference_deviation_bps=int(
            os.getenv("IAT_CHECKOUT_MAX_REFERENCE_DEVIATION_BPS", "500")
        ),
        allowed_raydium_pools=pools,
        treasury_program_id=os.getenv("IAT_TREASURY_PROGRAM_ID", "").strip(),
        treasury_vault=os.getenv("IAT_TREASURY_IAT_VAULT", "").strip(),
    )


def init_checkout_db() -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS universal_checkout_quotes (
                quote_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                buyer_wallet TEXT NOT NULL,
                input_asset TEXT NOT NULL,
                route TEXT NOT NULL,
                required_iat TEXT NOT NULL,
                state TEXT NOT NULL,
                intent_hash TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                quote_payload TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                tx_signature TEXT,
                execution_evidence TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_checkout_wallet_created
            ON universal_checkout_quotes (buyer_wallet, created_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_checkout_order_state
            ON universal_checkout_quotes (order_id, state)
            """
        )
        try:
            if database.USE_POSTGRES:
                cur.execute(
                    "ALTER TABLE universal_checkout_quotes "
                    "ADD COLUMN IF NOT EXISTS execution_evidence TEXT"
                )
            else:
                cur.execute(
                    "ALTER TABLE universal_checkout_quotes "
                    "ADD COLUMN execution_evidence TEXT"
                )
        except Exception:
            pass
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_checkout_tx_signature
            ON universal_checkout_quotes (tx_signature)
            WHERE tx_signature IS NOT NULL
            """
        )
        conn.commit()
    finally:
        release_conn(conn)
    init_checkout_delivery_db()
    init_compensation_db()
    init_delivery_receipt_db()


def _public_quote(row: Any) -> dict[str, Any]:
    value = dict(row)
    payload = json.loads(value.pop("quote_payload"))
    payload.pop("_provider_payload", None)
    payload.update(
        {
            "quote_id": value["quote_id"],
            "state": value["state"],
            "created_at": value["created_at"],
            "expires_at": value["expires_at"],
        }
    )
    return payload


def _get_quote(quote_id: str) -> dict[str, Any] | None:
    init_checkout_db()
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"SELECT * FROM universal_checkout_quotes WHERE quote_id = {p}",
            (quote_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        release_conn(conn)


def _sync_delivery_receipt(row: dict[str, Any], delivery: dict[str, Any]) -> dict[str, Any]:
    if delivery.get("state") == "completed":
        payload = delivery.get("result")
        if isinstance(payload, dict):
            publish_delivery_payload(
                quote_id=row["quote_id"],
                order_id=row["order_id"],
                payload=payload,
            )
    return public_delivery_receipt(get_delivery_receipt(row["quote_id"]))


def _get_by_idempotency(key: str) -> dict[str, Any] | None:
    init_checkout_db()
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"SELECT * FROM universal_checkout_quotes WHERE idempotency_key = {p}",
            (key,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        release_conn(conn)


def _active_quote_for_order(order_id: str, now: int) -> dict[str, Any] | None:
    init_checkout_db()
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        states = ", ".join([p] * len(ACTIVE_STATES))
        cur.execute(
            f"""
            SELECT * FROM universal_checkout_quotes
            WHERE order_id = {p} AND expires_at >= {p}
              AND state IN ({states})
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (order_id, now, *ACTIVE_STATES),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        release_conn(conn)


def _reserved_iat(
    *,
    buyer_wallet: str | None = None,
    route: str | None = None,
    now: int,
) -> Decimal:
    init_checkout_db()
    day_start = now - (now % 86400)
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        states = ", ".join([p] * len(ACTIVE_STATES))
        values: list[Any] = [day_start, now, *ACTIVE_STATES]
        wallet_filter = ""
        if buyer_wallet:
            wallet_filter = f" AND buyer_wallet = {p}"
            values.append(buyer_wallet)
        route_filter = ""
        if route:
            route_filter = f" AND route = {p}"
            values.append(route)
        cur.execute(
            f"""
            SELECT required_iat FROM universal_checkout_quotes
            WHERE created_at >= {p} AND expires_at >= {p}
              AND state IN ({states}){wallet_filter}{route_filter}
            """,
            tuple(values),
        )
        return sum(
            (decimal_value(dict(row)["required_iat"], "reserved_iat") for row in cur.fetchall()),
            Decimal("0"),
        )
    finally:
        release_conn(conn)


def _asset_snapshot(symbol: str) -> AssetSnapshot:
    normalized = symbol.strip().upper()
    registry = _json_env("IAT_CHECKOUT_ASSETS_JSON")
    value = registry.get(normalized)
    if not isinstance(value, dict):
        raise CheckoutRejected("unsupported_input_asset")
    if (
        normalized == "USDC"
        and _bool_env("IAT_CHECKOUT_DEVNET_FIXED_USDC_ENABLED")
        and str(value.get("mint") or "") == DEVNET_CIRCLE_USDC_MINT
        and str(value.get("oracle") or "") == DEVNET_FIXED_USDC_ORACLE
        and decimal_value(value.get("usd_price"), "asset_usd_price") == Decimal("1")
    ):
        value = dict(value)
        value["observed_at"] = int(time.time())
    return AssetSnapshot.from_mapping(normalized, value)


def _raydium_snapshot(symbol: str) -> RaydiumSnapshot | None:
    registry = _json_env("IAT_RAYDIUM_QUOTES_JSON")
    value = registry.get(symbol.strip().upper())
    return RaydiumSnapshot.from_mapping(value) if isinstance(value, dict) else None


def _raydium_client(maximum_input_minor: int) -> RaydiumClient:
    return RaydiumClient(
        RaydiumPolicy(
            timeout_seconds=float(os.getenv("IAT_RAYDIUM_TIMEOUT_SECONDS", "8")),
            slippage_bps=int(os.getenv("IAT_RAYDIUM_SLIPPAGE_BPS", "100")),
            max_price_impact_bps=int(
                os.getenv("IAT_RAYDIUM_MAX_PRICE_IMPACT_BPS", "300")
            ),
            max_input_amount_minor=maximum_input_minor,
            allowed_pools=tuple(
                value.strip()
                for value in os.getenv("IAT_RAYDIUM_ALLOWED_POOLS", "").split(",")
                if value.strip()
            ),
            allowed_programs=tuple(
                value.strip()
                for value in os.getenv("IAT_RAYDIUM_ALLOWED_PROGRAMS", "").split(",")
                if value.strip()
            ),
            compute_unit_price_micro_lamports=int(
                os.getenv("IAT_RAYDIUM_COMPUTE_UNIT_PRICE_MICRO_LAMPORTS", "50000")
            ),
        )
    )


def _live_raydium_quote(
    *,
    order: dict[str, Any],
    asset: AssetSnapshot,
    policy: CheckoutPolicy,
) -> tuple[RaydiumSnapshot, dict[str, Any]]:
    required_iat = decimal_value(order.get("price"), "order_price")
    expected_input = required_iat * policy.iat_usd_reference_price / asset.usd_price
    maximum_multiplier = Decimal(
        10_000
        + policy.max_reference_deviation_bps
        + int(os.getenv("IAT_RAYDIUM_SLIPPAGE_BPS", "100"))
    ) / Decimal(10_000)
    maximum_input_minor = int(
        (
            expected_input
            * maximum_multiplier
            * (Decimal(10) ** asset.decimals)
        ).quantize(Decimal("1"), rounding=ROUND_UP)
    )
    asset_registry = _json_env("IAT_CHECKOUT_ASSETS_JSON")
    asset_config = asset_registry.get(asset.symbol)
    if not isinstance(asset_config, dict):
        raise RaydiumError("asset_execution_configuration_missing")
    output_minor = int(
        (required_iat * (Decimal(10) ** IAT_DECIMALS)).quantize(
            Decimal("1"),
            rounding=ROUND_UP,
        )
    )
    client = _raydium_client(maximum_input_minor)
    pool_liquidity = client.fetch_pool_liquidity_usd(
        input_mint=asset.mint,
        output_mint=IAT_TOKEN_ADDRESS,
    )
    validated = client.quote_exact_output(
        input_mint=asset.mint,
        output_mint=IAT_TOKEN_ADDRESS,
        output_amount_minor=output_minor,
        input_decimals=asset.decimals,
        output_decimals=IAT_DECIMALS,
        pool_liquidity_usd=pool_liquidity,
    )
    return validated.snapshot, {
        "provider": "raydium_trade_api_v2",
        "quote_response": validated.response,
        "maximum_input_minor": maximum_input_minor,
    }


def _treasury_instruction_plan(payload: dict[str, Any], order_id: str) -> dict[str, Any]:
    assets = _json_env("IAT_CHECKOUT_ASSETS_JSON")
    asset = assets.get(str(payload["input"]["asset"]).upper())
    if not isinstance(asset, dict):
        raise SolanaPlanError("asset_execution_configuration_missing")
    try:
        ratio_numerator = int(asset["onchain_ratio_numerator"])
        ratio_denominator = int(asset["onchain_ratio_denominator"])
        expected_input = (
            int(payload["output"]["amount_minor"]) * ratio_numerator
            + ratio_denominator
            - 1
        ) // ratio_denominator
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise SolanaPlanError("onchain_price_ratio_missing_or_invalid") from exc
    if ratio_numerator <= 0 or ratio_denominator <= 0:
        raise SolanaPlanError("onchain_price_ratio_missing_or_invalid")
    if expected_input != int(payload["input"]["amount_minor"]):
        raise SolanaPlanError("quote_does_not_match_onchain_price_ratio")
    input_program = str(asset.get("token_program") or SPL_TOKEN_PROGRAM_ID)
    iat_program = os.getenv(
        "IAT_IAT_TOKEN_PROGRAM",
        str(SPL_TOKEN_PROGRAM_ID),
    )
    try:
        buyer = Pubkey.from_string(payload["buyer_wallet"])
        buyer_input = get_associated_token_address(
            buyer,
            Pubkey.from_string(payload["input"]["mint"]),
            token_program_id=Pubkey.from_string(input_program),
        )
        buyer_iat = get_associated_token_address(
            buyer,
            Pubkey.from_string(payload["output"]["mint"]),
            token_program_id=Pubkey.from_string(iat_program),
        )
    except Exception as exc:
        raise SolanaPlanError("invalid_buyer_token_account_derivation") from exc
    return build_direct_usdc_purchase_plan(
        quote=payload,
        order_id=order_id,
        program_id=os.getenv("IAT_TREASURY_PROGRAM_ID", ""),
        quote_authority=os.getenv("IAT_TREASURY_QUOTE_AUTHORITY", ""),
        treasury_iat_vault=os.getenv("IAT_TREASURY_IAT_VAULT", ""),
        treasury_input_vault=str(asset.get("treasury_vault") or ""),
        buyer_input_account=str(buyer_input),
        buyer_iat_account=str(buyer_iat),
        input_token_program=input_program,
        iat_token_program=iat_program,
    )


def _raydium_transaction_plan(payload: dict[str, Any]) -> dict[str, Any]:
    provider = payload.get("_provider_payload")
    if not isinstance(provider, dict) or provider.get("provider") != "raydium_trade_api_v2":
        raise RaydiumError("raydium_live_quote_payload_missing")
    assets = _json_env("IAT_CHECKOUT_ASSETS_JSON")
    asset = assets.get(str(payload["input"]["asset"]).upper())
    if not isinstance(asset, dict):
        raise RaydiumError("asset_execution_configuration_missing")
    input_program = Pubkey.from_string(
        str(asset.get("token_program") or SPL_TOKEN_PROGRAM_ID)
    )
    buyer_input = get_associated_token_address(
        Pubkey.from_string(payload["buyer_wallet"]),
        Pubkey.from_string(payload["input"]["mint"]),
        token_program_id=input_program,
    )
    return _raydium_client(int(provider["maximum_input_minor"])).build_exact_output_transaction(
        quote_response=provider["quote_response"],
        buyer_wallet=payload["buyer_wallet"],
        input_account=str(buyer_input),
        settlement_escrow=os.getenv("IAT_TREASURY_SETTLEMENT_ESCROW", ""),
        expected_input_mint=payload["input"]["mint"],
        expected_output_mint=payload["output"]["mint"],
        expected_output_amount_minor=int(payload["output"]["amount_minor"]),
    )


def _authorize_order(req: UniversalQuoteRequest | UniversalPrepareRequest, order: dict[str, Any]) -> None:
    expected_secret = str(order.get("buyer_secret") or "")
    expected_wallet = str(order.get("buyer_wallet") or "")
    if not expected_secret or not secrets.compare_digest(req.buyer_secret, expected_secret):
        raise HTTPException(status_code=403, detail="invalid_order_credential")
    if not expected_wallet or not secrets.compare_digest(req.buyer_wallet, expected_wallet):
        raise HTTPException(status_code=403, detail="invalid_order_credential")


@contextmanager
def _reservation_guard():
    """Serialize cap checks across threads and PostgreSQL application workers."""

    with _LOCAL_RESERVATION_LOCK:
        lock_connection = None
        try:
            if database.USE_POSTGRES:
                lock_connection = get_conn()
                cursor = lock_connection.cursor()
                cursor.execute(
                    "SELECT pg_advisory_lock(%s)",
                    (_POSTGRES_RESERVATION_LOCK_ID,),
                )
            yield
        finally:
            if lock_connection is not None:
                try:
                    cursor = lock_connection.cursor()
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (_POSTGRES_RESERVATION_LOCK_ID,),
                    )
                finally:
                    release_conn(lock_connection)


def _create_universal_quote(
    req: UniversalQuoteRequest,
    idempotency_key: str | None,
):
    if not idempotency_key or not 16 <= len(idempotency_key) <= 128:
        raise HTTPException(status_code=400, detail="valid_idempotency_key_required")
    order = get_order_db(req.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)

    request_hash = canonical_hash(
        {
            "order_id": req.order_id,
            "buyer_wallet": req.buyer_wallet,
            "input_asset": req.input_asset.upper(),
        }
    )
    previous = _get_by_idempotency(idempotency_key)
    if previous:
        if previous["request_hash"] != request_hash:
            raise HTTPException(status_code=409, detail="idempotency_key_conflict")
        return _public_quote(previous)

    now = int(time.time())
    active = _active_quote_for_order(req.order_id, now)
    if active:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "order_has_active_checkout_quote",
                "quote_id": active["quote_id"],
                "state": active["state"],
                "expires_at": active["expires_at"],
            },
        )
    asset_snapshot = None
    checkout_policy = None
    provider_payload = None
    try:
        asset_snapshot = _asset_snapshot(req.input_asset)
        checkout_policy = _quote_signer_compatible_policy(load_checkout_policy())
        result = quote_hybrid_checkout(
            order=order,
            buyer_wallet=req.buyer_wallet,
            asset=asset_snapshot,
            policy=checkout_policy,
            wallet_iat_today=_reserved_iat(buyer_wallet=req.buyer_wallet, now=now),
            treasury_iat_today=_reserved_iat(route="treasury", now=now),
            raydium=_raydium_snapshot(req.input_asset),
            now=now,
        )
    except CheckoutRejected as exc:
        live_enabled = _bool_env("IAT_RAYDIUM_LIVE_ENABLED")
        if (
            exc.code == "no_safe_checkout_route"
            and live_enabled
            and checkout_policy is not None
            and checkout_policy.raydium_enabled
            and asset_snapshot is not None
        ):
            try:
                live_snapshot, provider_payload = _live_raydium_quote(
                    order=order,
                    asset=asset_snapshot,
                    policy=checkout_policy,
                )
                result = quote_hybrid_checkout(
                    order=order,
                    buyer_wallet=req.buyer_wallet,
                    asset=asset_snapshot,
                    policy=replace(
                        checkout_policy,
                        quote_ttl_seconds=min(
                            checkout_policy.quote_ttl_seconds,
                            25,
                        ),
                    ),
                    wallet_iat_today=_reserved_iat(
                        buyer_wallet=req.buyer_wallet,
                        now=now,
                    ),
                    treasury_iat_today=_reserved_iat(
                        route="treasury",
                        now=now,
                    ),
                    raydium=live_snapshot,
                    now=now,
                )
            except (CheckoutRejected, RaydiumError) as live_exc:
                code = getattr(live_exc, "code", "raydium_quote_failed")
                details = getattr(live_exc, "details", {})
                raise HTTPException(
                    status_code=422,
                    detail={"code": code, "details": details},
                ) from live_exc
        else:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code, "details": exc.details},
            ) from exc
    if provider_payload is not None:
        result["_provider_payload"] = provider_payload

    quote_id = f"uq_{uuid.uuid4().hex}"
    result["quote_id"] = quote_id
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            INSERT INTO universal_checkout_quotes (
                quote_id, order_id, buyer_wallet, input_asset, route,
                required_iat, state, intent_hash, request_hash, idempotency_key,
                quote_payload, created_at, expires_at, updated_at
            ) VALUES ({", ".join([p] * 14)})
            """,
            (
                quote_id,
                req.order_id,
                req.buyer_wallet,
                req.input_asset.upper(),
                result["route"],
                result["output"]["amount"],
                "quoted",
                result["intent_hash"],
                request_hash,
                idempotency_key,
                json.dumps(result, sort_keys=True),
                result["created_at"],
                result["expires_at"],
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        previous = _get_by_idempotency(idempotency_key)
        if previous and previous["request_hash"] == request_hash:
            return _public_quote(previous)
        raise
    finally:
        release_conn(conn)
    public_result = dict(result)
    public_result.pop("_provider_payload", None)
    return public_result


@router.post("/quote")
def create_universal_quote(
    req: UniversalQuoteRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    with _reservation_guard():
        return _create_universal_quote(req, idempotency_key)


@router.post("/{quote_id}/prepare")
def prepare_universal_checkout(quote_id: str, req: UniversalPrepareRequest):
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)
    if not secrets.compare_digest(req.buyer_wallet, row["buyer_wallet"]):
        raise HTTPException(status_code=403, detail="invalid_order_credential")
    now = int(time.time())
    if now >= int(row["expires_at"]):
        raise HTTPException(status_code=410, detail="quote_expired")
    if row["state"] == "prepared" and row.get("execution_evidence"):
        evidence = json.loads(row["execution_evidence"])
        return evidence["prepared_response"]
    if row["state"] != "quoted":
        raise HTTPException(status_code=409, detail="quote_not_preparable")

    payload = json.loads(row["quote_payload"])
    response = {
        "status": "prepared",
        "quote_id": quote_id,
        "intent_hash": row["intent_hash"],
        "route": row["route"],
        "expires_at": row["expires_at"],
        "transaction_contract": {
            "network": "solana",
            "buyer_signer": row["buyer_wallet"],
            "input": payload["input"],
            "minimum_iat_output": payload["output"],
            "iat_destination": "buyer_associated_token_account",
            "order_id": row["order_id"],
            "atomic_execution_required": True,
            "simulation_required_before_submission": True,
        },
        "readiness": {
            "policy_and_reservation": "ready",
            "instruction_plan": "unavailable",
            "serialized_transaction": "buyer_wallet_must_add_blockhash_and_sign",
            "server_custody": False,
        },
    }
    proof: dict[str, Any] | None = None
    if row["route"] == "treasury":
        try:
            plan = _treasury_instruction_plan(
                payload,
                row["order_id"],
            )
            response["solana_instruction_plan"] = plan
            response["readiness"]["instruction_plan"] = "ready"
            replay = plan["anti_replay"]
            proof = {
                "buyer_wallet": row["buyer_wallet"],
                "program_id": plan["program_id"],
                "payment_intent": replay["payment_intent"],
                "order_hash_hex": replay["order_hash_hex"],
                "quote_hash_hex": replay["quote_hash_hex"],
                "input_mint": payload["input"]["mint"],
                "input_amount": int(payload["input"]["amount_minor"]),
                "iat_amount": int(payload["output"]["amount_minor"]),
                "nonce": int(replay["nonce"]),
            }
            if plan.get("delivery_mode") == "direct_to_buyer":
                proof["delivery_mode"] = "direct_to_buyer"
                proof["iat_destination"] = plan["display"]["iat_destination"]
            proof["quote_authority"] = plan["quote_authority"]
        except (CheckoutRejected, SolanaPlanError) as exc:
            response["readiness"]["instruction_plan"] = f"configuration_error:{exc}"
    else:
        try:
            plan = _raydium_transaction_plan(payload)
            response["raydium_transaction"] = plan
            response["readiness"]["instruction_plan"] = "ready"
            response["readiness"]["serialized_transaction"] = (
                "ready_for_buyer_simulation_and_signature"
            )
            proof = {
                "buyer_wallet": row["buyer_wallet"],
                "message_hash": message_hash_from_transaction_base64(
                    plan["transaction_base64"]
                ),
            }
        except (CheckoutRejected, RaydiumError, KeyError, ValueError) as exc:
            response["readiness"]["instruction_plan"] = f"configuration_error:{exc}"
    if proof is None:
        return response

    stored_evidence = {
        "proof": proof,
        "prepared_response": response,
    }
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            UPDATE universal_checkout_quotes
            SET state = {p}, execution_evidence = {p}, updated_at = {p}
            WHERE quote_id = {p} AND state = {p}
            """,
            (
                "prepared",
                json.dumps(stored_evidence, sort_keys=True),
                now,
                quote_id,
                "quoted",
            ),
        )
        if cur.rowcount != 1:
            conn.rollback()
            winner = _get_quote(quote_id)
            if winner and winner.get("execution_evidence"):
                return json.loads(winner["execution_evidence"])["prepared_response"]
            raise HTTPException(status_code=409, detail="quote_prepare_conflict")
        conn.commit()
    finally:
        release_conn(conn)
    return response


def _authorize_with_quote_signer(
    *,
    quote_id: str,
    transaction_base64: str,
    instruction_plan: dict[str, Any],
    expires_at: int,
) -> dict[str, Any]:
    if not _bool_env("IAT_QUOTE_SIGNER_CLIENT_ENABLED"):
        raise HTTPException(status_code=503, detail="quote_signer_disabled")
    url = os.getenv("IAT_QUOTE_SIGNER_URL", "").strip().rstrip("/")
    if not url.startswith("https://") and not (
        _bool_env("IAT_QUOTE_SIGNER_ALLOW_HTTP_PRIVATE")
        and url.startswith("http://")
    ):
        raise HTTPException(status_code=503, detail="quote_signer_url_invalid")
    secret = os.getenv("IAT_QUOTE_SIGNER_SHARED_SECRET", "").encode()
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="quote_signer_secret_unavailable")
    message_hash = hashlib.sha256(transaction_base64.encode()).hexdigest()
    payload = {
        "request_id": f"sign_{hashlib.sha256(f'{quote_id}:{message_hash}'.encode()).hexdigest()[:40]}",
        "quote_id": quote_id,
        "expires_at": int(expires_at),
        "transaction_base64": transaction_base64,
        "instruction_plan": instruction_plan,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret,
        timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    try:
        response = requests.post(
            f"{url}/v1/sign",
            data=raw,
            headers={
                "Content-Type": "application/json",
                "X-IAT-Signer-Timestamp": timestamp,
                "X-IAT-Signer-Signature": signature,
            },
            timeout=min(
                max(float(os.getenv("IAT_QUOTE_SIGNER_TIMEOUT_SECONDS", "8")), 1),
                15,
            ),
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=503, detail="quote_signer_unavailable") from exc
    if (
        not isinstance(result, dict)
        or result.get("status") != "signed"
        or result.get("quote_id") != quote_id
        or result.get("quote_authority") != instruction_plan.get("quote_authority")
        or int(result.get("expires_at") or 0) != int(expires_at)
        or not isinstance(result.get("transaction_base64"), str)
    ):
        raise HTTPException(status_code=503, detail="quote_signer_response_invalid")
    try:
        verified_message_hash = verify_quote_authorization(
            original_transaction_base64=transaction_base64,
            authorized_transaction_base64=result["transaction_base64"],
            quote_authority=str(instruction_plan["quote_authority"]),
        )
    except (QuoteSigningRejected, KeyError) as exc:
        raise HTTPException(status_code=503, detail="quote_signer_response_invalid") from exc
    if result.get("message_hash") != verified_message_hash:
        raise HTTPException(status_code=503, detail="quote_signer_response_invalid")
    return result


@router.post("/{quote_id}/authorize")
def authorize_universal_checkout(
    quote_id: str,
    req: UniversalAuthorizeRequest,
):
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)
    if not secrets.compare_digest(req.buyer_wallet, row["buyer_wallet"]):
        raise HTTPException(status_code=403, detail="invalid_order_credential")
    if row["state"] != "prepared" or not row.get("execution_evidence"):
        raise HTTPException(status_code=409, detail="quote_not_authorizable")
    if int(time.time()) >= int(row["expires_at"]):
        raise HTTPException(status_code=410, detail="quote_expired")
    evidence = json.loads(row["execution_evidence"])
    prepared = evidence.get("prepared_response")
    plan = prepared.get("solana_instruction_plan") if isinstance(prepared, dict) else None
    if not isinstance(plan, dict) or plan.get("protocol_authorization_signature_required") is not True:
        raise HTTPException(status_code=409, detail="quote_authorization_plan_unavailable")
    result = _authorize_with_quote_signer(
        quote_id=quote_id,
        transaction_base64=req.transaction_base64,
        instruction_plan=plan,
        expires_at=int(row["expires_at"]),
    )
    return {
        "status": "authorized",
        "quote_id": quote_id,
        "transaction_base64": result["transaction_base64"],
        "message_hash": result["message_hash"],
        "quote_authority": result["quote_authority"],
        "expires_at": result["expires_at"],
        "buyer_signature_required": True,
        "next_step": "buyer_wallet_must_review_simulate_sign_and_submit",
        "idempotent": bool(result.get("idempotent")),
    }


@router.post("/{quote_id}/submit")
def submit_universal_checkout(quote_id: str, req: UniversalSubmitRequest):
    try:
        Signature.from_string(req.tx_signature)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid_transaction_signature") from exc
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)
    if row["state"] == "submitted":
        if secrets.compare_digest(str(row.get("tx_signature") or ""), req.tx_signature):
            return {
                "status": "submitted",
                "quote_id": quote_id,
                "tx_signature": req.tx_signature,
                "idempotent": True,
            }
        raise HTTPException(status_code=409, detail="quote_already_submitted")
    if row["state"] != "prepared" or not row.get("execution_evidence"):
        raise HTTPException(status_code=409, detail="quote_not_submittable")

    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        cur.execute(
            f"""
            UPDATE universal_checkout_quotes
            SET state = {p}, tx_signature = {p}, updated_at = {p}
            WHERE quote_id = {p} AND state = {p}
            """,
            ("submitted", req.tx_signature, int(time.time()), quote_id, "prepared"),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=409, detail="transaction_claim_conflict")
        conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail="transaction_signature_already_claimed") from exc
    finally:
        release_conn(conn)
    return {
        "status": "submitted",
        "quote_id": quote_id,
        "tx_signature": req.tx_signature,
        "next_step": f"/payments/v1/universal/{quote_id}/confirm",
        "idempotent": False,
    }


def _checkout_verifier() -> SolanaCheckoutVerifier:
    rpc_url = (
        os.getenv("IAT_CHECKOUT_SOLANA_RPC_URL")
        or os.getenv("IAT_SOLANA_RPC_URL")
        or ""
    )
    if not rpc_url:
        raise CheckoutVerificationError("checkout_rpc_not_configured", retryable=True)
    return SolanaCheckoutVerifier(
        rpc_url,
        timeout_seconds=float(os.getenv("IAT_CHECKOUT_RPC_TIMEOUT_SECONDS", "10")),
    )


def _finalize_checkout(row: dict[str, Any], proof: dict[str, Any]) -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        p = qmark()
        signature = row["tx_signature"]
        now = int(time.time())
        if database.USE_POSTGRES:
            cur.execute(
                f"""
                INSERT INTO processed_txs (tx_signature, processed_at)
                VALUES ({p}, {p}) ON CONFLICT (tx_signature) DO NOTHING
                """,
                (signature, now),
            )
        else:
            cur.execute(
                f"""
                INSERT OR IGNORE INTO processed_txs (tx_signature, processed_at)
                VALUES ({p}, {p})
                """,
                (signature, now),
            )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=409, detail="transaction_already_processed")
        cur.execute(
            f"""
            UPDATE universal_checkout_quotes
            SET state = {p}, updated_at = {p}
            WHERE quote_id = {p} AND state = {p} AND tx_signature = {p}
            """,
            ("confirmed", now, row["quote_id"], "submitted", signature),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=409, detail="confirmation_state_conflict")
        cur.execute(
            f"""
            UPDATE orders SET status = {p}, tx_signature = {p}, updated_at = {p}
            WHERE order_id = {p} AND used = {p}
            """,
            ("paid", signature, now, row["order_id"], 0),
        )
        enqueue_delivery_tx(
            cur,
            quote_id=row["quote_id"],
            order_id=row["order_id"],
            tx_signature=signature,
            now=now,
        )
        conn.commit()
    finally:
        release_conn(conn)


@router.post("/{quote_id}/confirm")
def confirm_universal_checkout(quote_id: str, req: UniversalPrepareRequest):
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)
    if row["state"] == "confirmed":
        delivery = run_checkout_delivery(quote_id)
        return {
            "status": "confirmed",
            "quote_id": quote_id,
            "tx_signature": row["tx_signature"],
            "delivery": delivery,
            "final_receipt": _sync_delivery_receipt(row, delivery),
            "idempotent": True,
        }
    if row["state"] != "submitted" or not row.get("execution_evidence"):
        raise HTTPException(status_code=409, detail="quote_not_confirmable")
    evidence = json.loads(row["execution_evidence"])
    try:
        proof = _checkout_verifier().verify(
            signature=row["tx_signature"],
            route=row["route"],
            evidence=evidence["proof"],
        )
    except CheckoutVerificationError as exc:
        if exc.retryable:
            return {
                "status": "pending",
                "quote_id": quote_id,
                "reason": exc.code,
                "retryable": True,
            }
        conn = get_conn()
        try:
            cur = conn.cursor()
            p = qmark()
            cur.execute(
                f"""
                UPDATE universal_checkout_quotes
                SET state = {p}, updated_at = {p}
                WHERE quote_id = {p} AND state = {p}
                """,
                ("failed", int(time.time()), quote_id, "submitted"),
            )
            conn.commit()
        finally:
            release_conn(conn)
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "retryable": False},
        ) from exc
    _finalize_checkout(row, proof)
    delivery = run_checkout_delivery(quote_id)
    return {
        **proof,
        "quote_id": quote_id,
        "order_id": row["order_id"],
        "payment_verified": True,
        "delivery": delivery,
        "final_receipt": _sync_delivery_receipt(row, delivery),
        "idempotent": False,
    }


@router.post("/{quote_id}/deliver")
def deliver_universal_checkout(quote_id: str, req: UniversalPrepareRequest):
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)
    if row["state"] != "confirmed":
        raise HTTPException(status_code=409, detail="payment_not_confirmed")
    current_delivery = public_delivery_status(quote_id)
    if current_delivery.get("state") == "review_required":
        resume_review_required_delivery(quote_id)
    elif current_delivery.get("state") == "retryable_failure":
        accelerate_foundation_retry(quote_id)
    delivery = run_checkout_delivery(quote_id)
    return {
        "status": "delivery_checked",
        "quote_id": quote_id,
        "payment_verified": True,
        "delivery": delivery,
        "final_receipt": _sync_delivery_receipt(row, delivery),
    }


@router.post("/{quote_id}/delivery-destination")
def set_universal_delivery_destination(
    quote_id: str,
    req: UniversalDeliveryDestinationRequest,
):
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)
    if not secrets.compare_digest(req.buyer_wallet, row["buyer_wallet"]):
        raise HTTPException(status_code=403, detail="invalid_order_credential")
    try:
        receipt = configure_delivery_receipt(
            quote_id=quote_id,
            order_id=row["order_id"],
            channel=req.channel,
            destination=req.destination,
        )
    except DeliveryReceiptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "delivery_destination_configured", "quote_id": quote_id, "final_receipt": receipt}


@router.post("/{quote_id}/delivery/decision")
def decide_universal_delivery(
    quote_id: str,
    req: UniversalDeliveryDecisionRequest,
):
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)
    if row["state"] != "confirmed":
        raise HTTPException(status_code=409, detail="payment_not_confirmed")
    try:
        receipt = acknowledge_delivery(
            quote_id=quote_id,
            decision=req.decision,
            dispute_code=req.dispute_code,
            message=req.message,
        )
    except DeliveryReceiptError as exc:
        code = str(exc)
        status_code = 404 if code == "delivery_receipt_not_found" else 409
        if code.startswith("valid_") or code in {"dispute_explanation_required", "invalid_delivery_decision"}:
            status_code = 422
        raise HTTPException(status_code=status_code, detail=code) from exc
    return {"status": f"delivery_{req.decision}", "quote_id": quote_id, "final_receipt": receipt}


@router.get("/delivery-receipts/{receipt_token}")
def get_delivery_receipt_by_link(receipt_token: str):
    receipt = get_delivery_receipt_by_token(receipt_token)
    if not receipt:
        raise HTTPException(status_code=404, detail="delivery_receipt_not_found")
    public = public_delivery_receipt(receipt)
    public.pop("receipt_token", None)
    return {
        "status": "delivery_receipt_found",
        "quote_id": receipt["quote_id"],
        "final_receipt": public,
        "opening_does_not_accept_delivery": True,
    }


@router.get("/delivery-receipts/{receipt_token}/inbox")
def open_delivery_inbox_by_link(receipt_token: str, response: Response):
    try:
        inbox = open_delivery_inbox(receipt_token)
    except DeliveryReceiptError as exc:
        code = str(exc)
        status_code = 404 if code == "delivery_receipt_not_found" else 409
        raise HTTPException(status_code=status_code, detail=code) from exc
    response.headers["Cache-Control"] = "no-store, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return {"status": "delivery_inbox_opened", **inbox}


@router.post("/delivery-receipts/{receipt_token}/decision")
def decide_delivery_by_link(
    receipt_token: str,
    req: PublicDeliveryDecisionRequest,
):
    stored = get_delivery_receipt_by_token(receipt_token)
    if not stored:
        raise HTTPException(status_code=404, detail="delivery_receipt_not_found")
    try:
        receipt = acknowledge_delivery(
            quote_id=stored["quote_id"],
            decision=req.decision,
            dispute_code=req.dispute_code,
            message=req.message,
        )
    except DeliveryReceiptError as exc:
        code = str(exc)
        status_code = 409
        if code.startswith("valid_") or code in {
            "dispute_explanation_required",
            "invalid_delivery_decision",
        }:
            status_code = 422
        raise HTTPException(status_code=status_code, detail=code) from exc
    receipt.pop("receipt_token", None)
    return {
        "status": f"delivery_{req.decision}",
        "quote_id": stored["quote_id"],
        "final_receipt": receipt,
    }


@router.post("/delivery-events/mailjet")
def receive_mailjet_delivery_event(
    payload: dict[str, Any] | list[dict[str, Any]],
    authorization: str | None = Header(default=None),
):
    _authorize_mailjet_event(authorization)
    events = payload if isinstance(payload, list) else [payload]
    if not events or len(events) > 100:
        raise HTTPException(status_code=422, detail="valid_mailjet_event_batch_required")
    recorded = 0
    ignored = 0
    for item in events:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="valid_mailjet_event_required")
        campaign = str(item.get("customcampaign") or "")
        if not campaign.startswith("cdr_"):
            ignored += 1
            continue
        try:
            record_email_provider_event(
                receipt_token=campaign,
                recipient=str(item.get("email") or ""),
                event=str(item.get("event") or ""),
                event_at=int(item.get("time") or 0),
                provider_message_id=str(
                    item.get("MessageID")
                    or item.get("message_id")
                    or item.get("mj_campaign_id")
                    or ""
                ),
                reason=" ".join(
                    value
                    for value in (
                        str(item.get("error_related_to") or "").strip(),
                        str(item.get("error") or "").strip(),
                    )
                    if value
                ),
            )
        except (TypeError, ValueError, DeliveryReceiptError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        recorded += 1
    return {
        "status": "mailjet_events_processed",
        "recorded": recorded,
        "ignored": ignored,
    }


@router.post("/{quote_id}/evidence-readiness")
def checkout_evidence_readiness(quote_id: str, req: UniversalPrepareRequest):
    """Read-only, authenticated preflight over the stored buyer query."""
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)

    from iat.api.multi_exec import (
        foundation_direct_evidence_readiness,
    )

    stored_query = str(order.get("query") or "")
    readiness = foundation_direct_evidence_readiness(stored_query, limit=5)
    return {
        "status": readiness["status"],
        "quote_id": quote_id,
        "search_query": readiness["search_query"],
        "provider": readiness["provider"],
        "source_count": readiness["source_count"],
        "candidate_claim_count": readiness["candidate_claim_count"],
        "verified_claim_count": readiness["verified_claim_count"],
        "rejected_claim_count": readiness["rejected_claim_count"],
        "uncertain_claim_count": readiness["uncertain_claim_count"],
        "source_quality": readiness["source_quality"],
        "read_only": True,
    }


@router.post("/{quote_id}/compensation/request")
def request_universal_checkout_compensation(
    quote_id: str,
    req: UniversalPrepareRequest,
):
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(req, order)
    if row["state"] != "confirmed":
        raise HTTPException(status_code=409, detail="payment_not_confirmed")
    try:
        compensation = request_compensation(
            quote_id,
            requested_by="authenticated_buyer",
        )
    except ValueError as exc:
        code = str(exc)
        status_code = 404 if code == "checkout_delivery_not_found" else 409
        raise HTTPException(status_code=status_code, detail=code) from exc
    return {
        "status": "compensation_requested",
        "quote_id": quote_id,
        "payment_verified": True,
        "compensation": public_compensation(compensation),
        "idempotent": compensation.get("idempotent", False),
    }


@router.get("/buyer-inbox")
def get_buyer_delivery_inbox(
    response: Response,
    buyer_wallet: str | None = Header(default=None, alias="X-IAT-Buyer-Wallet"),
    buyer_secret: str | None = Header(default=None, alias="X-IAT-Order-Secret"),
    cursor: str | None = None,
    limit: int = 20,
):
    if not buyer_wallet or not buyer_secret:
        raise HTTPException(status_code=403, detail="invalid_order_credential")
    before_configured_at, before_quote_id = _decode_inbox_cursor(cursor)
    authorized, rows = list_buyer_delivery_receipts(
        buyer_wallet=buyer_wallet,
        buyer_secret=buyer_secret,
        before_configured_at=before_configured_at,
        before_quote_id=before_quote_id,
        limit=limit,
    )
    if not authorized:
        raise HTTPException(status_code=403, detail="invalid_order_credential")
    safe_limit = max(1, min(int(limit), 100))
    selected = rows[:safe_limit]
    public_site = os.getenv(
        "IAT_PUBLIC_SITE_URL", "https://iat-protocol.pages.dev"
    ).strip().rstrip("/")
    items = []
    for row in selected:
        public = public_delivery_receipt(row)
        token = str(public["receipt_token"])
        items.append(
            {
                "quote_id": row["quote_id"],
                "order_id": row["order_id"],
                "delivery_url": f"{public_site}/delivery/#receipt={token}",
                "final_receipt": public,
            }
        )
    next_cursor = None
    if len(rows) > safe_limit and selected:
        last = selected[-1]
        next_cursor = _encode_inbox_cursor(last["configured_at"], last["quote_id"])
    response.headers["Cache-Control"] = "no-store, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return {
        "status": "buyer_inbox_found",
        "count": len(items),
        "items": items,
        "next_cursor": next_cursor,
    }


@router.get("/buyer-inbox/{quote_id}")
def get_authenticated_buyer_inbox_item(
    quote_id: str,
    response: Response,
    buyer_wallet: str | None = Header(default=None, alias="X-IAT-Buyer-Wallet"),
    buyer_secret: str | None = Header(default=None, alias="X-IAT-Order-Secret"),
):
    if not buyer_wallet or not buyer_secret:
        raise HTTPException(status_code=403, detail="invalid_order_credential")
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(
        UniversalPrepareRequest(
            buyer_wallet=buyer_wallet,
            buyer_secret=buyer_secret,
        ),
        order,
    )
    stored = get_delivery_receipt(quote_id)
    if not stored:
        raise HTTPException(status_code=404, detail="delivery_receipt_not_found")
    try:
        inbox = open_delivery_inbox(str(stored["receipt_token"]))
    except DeliveryReceiptError as exc:
        code = str(exc)
        status_code = 409 if code == "delivery_payload_not_ready" else 503
        raise HTTPException(status_code=status_code, detail=code) from exc
    inbox.pop("receipt_id", None)
    public = public_delivery_receipt(get_delivery_receipt(quote_id))
    public.pop("receipt_token", None)
    response.headers["Cache-Control"] = "no-store, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return {
        "status": "buyer_inbox_item_opened",
        "quote_id": quote_id,
        "final_receipt": public,
        "inbox": inbox,
    }


@router.get("/{quote_id}")
def get_universal_quote(
    quote_id: str,
    buyer_wallet: str | None = Header(default=None, alias="X-IAT-Buyer-Wallet"),
    buyer_secret: str | None = Header(default=None, alias="X-IAT-Order-Secret"),
):
    if not buyer_wallet or not buyer_secret:
        raise HTTPException(status_code=403, detail="invalid_order_credential")
    row = _get_quote(quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="quote_not_found")
    order = get_order_db(row["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    _authorize_order(
        UniversalPrepareRequest(
            buyer_wallet=buyer_wallet,
            buyer_secret=buyer_secret,
        ),
        order,
    )
    result = _public_quote(row)
    if result["state"] in ACTIVE_STATES and int(time.time()) >= int(row["expires_at"]):
        result["state"] = "expired"
    if result["state"] == "confirmed":
        result["delivery"] = public_delivery_status(quote_id)
        result["final_receipt"] = _sync_delivery_receipt(row, result["delivery"])
        result["compensation"] = public_compensation(get_compensation(quote_id))
    return result
