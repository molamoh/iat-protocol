"""Hybrid, order-bound checkout policy for IAT payments on Solana.

This module deliberately does not hold keys, sign transactions, or trust a DEX
as an oracle.  It produces deterministic payment intents which an on-chain
program can enforce atomically.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_UP
from typing import Any, Mapping

from iat.config import IAT_DECIMALS, IAT_TOKEN_ADDRESS

TERMINAL_ORDER_STATES = {"delivered", "completed", "settled", "refunded", "cancelled"}


class CheckoutRejected(ValueError):
    """A stable, safe rejection which may be returned to an API client."""

    def __init__(self, code: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


def decimal_value(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CheckoutRejected(f"invalid_{field}") from exc
    if not parsed.is_finite():
        raise CheckoutRejected(f"invalid_{field}")
    return parsed


def canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AssetSnapshot:
    symbol: str
    mint: str
    decimals: int
    usd_price: Decimal
    oracle: str
    observed_at: int

    @classmethod
    def from_mapping(cls, symbol: str, value: Mapping[str, Any]) -> "AssetSnapshot":
        normalized = symbol.strip().upper()
        mint = str(value.get("mint") or "").strip()
        oracle = str(value.get("oracle") or "").strip()
        decimals = int(value.get("decimals", -1))
        observed_at = int(value.get("observed_at", 0))
        usd_price = decimal_value(value.get("usd_price"), "asset_usd_price")
        if not normalized or not mint or not oracle:
            raise CheckoutRejected("invalid_asset_snapshot")
        if not 0 <= decimals <= 18 or usd_price <= 0 or observed_at <= 0:
            raise CheckoutRejected("invalid_asset_snapshot")
        return cls(normalized, mint, decimals, usd_price, oracle, observed_at)


@dataclass(frozen=True)
class RaydiumSnapshot:
    input_amount: Decimal
    output_iat: Decimal
    price_impact_bps: int
    pool_liquidity_usd: Decimal
    pool_id: str
    observed_at: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RaydiumSnapshot":
        return cls(
            input_amount=decimal_value(value.get("input_amount"), "raydium_input_amount"),
            output_iat=decimal_value(value.get("output_iat"), "raydium_output_iat"),
            price_impact_bps=int(value.get("price_impact_bps", -1)),
            pool_liquidity_usd=decimal_value(
                value.get("pool_liquidity_usd"), "raydium_pool_liquidity"
            ),
            pool_id=str(value.get("pool_id") or "").strip(),
            observed_at=int(value.get("observed_at", 0)),
        )


@dataclass(frozen=True)
class CheckoutPolicy:
    treasury_enabled: bool = False
    raydium_enabled: bool = False
    quote_ttl_seconds: int = 60
    oracle_max_age_seconds: int = 90
    treasury_spread_bps: int = 50
    max_order_iat: Decimal = Decimal("100")
    wallet_daily_iat_cap: Decimal = Decimal("250")
    treasury_daily_iat_cap: Decimal = Decimal("1000")
    treasury_inventory_iat: Decimal = Decimal("0")
    iat_usd_reference_price: Decimal = Decimal("0")
    max_raydium_price_impact_bps: int = 300
    min_raydium_liquidity_usd: Decimal = Decimal("10000")
    max_reference_deviation_bps: int = 500
    allowed_raydium_pools: tuple[str, ...] = ()
    treasury_program_id: str = ""
    treasury_vault: str = ""

    def validate(self) -> None:
        numeric = (
            self.quote_ttl_seconds,
            self.oracle_max_age_seconds,
            self.treasury_spread_bps,
            self.max_raydium_price_impact_bps,
            self.max_reference_deviation_bps,
        )
        if any(value < 0 for value in numeric):
            raise CheckoutRejected("invalid_checkout_policy")
        if not 10 <= self.quote_ttl_seconds <= 300:
            raise CheckoutRejected("invalid_quote_ttl")
        if self.treasury_enabled and (
            self.iat_usd_reference_price <= 0 or self.treasury_inventory_iat <= 0
        ):
            raise CheckoutRejected("treasury_not_funded_or_priced")


def _minor_units(amount: Decimal, decimals: int) -> int:
    scale = Decimal(10) ** decimals
    return int((amount * scale).quantize(Decimal("1"), rounding=ROUND_UP))


def _deviation_bps(left: Decimal, right: Decimal) -> int:
    if right <= 0:
        return 10**9
    return int(abs(left - right) * Decimal(10_000) / right)


def quote_hybrid_checkout(
    *,
    order: Mapping[str, Any],
    buyer_wallet: str,
    asset: AssetSnapshot,
    policy: CheckoutPolicy,
    wallet_iat_today: Decimal = Decimal("0"),
    treasury_iat_today: Decimal = Decimal("0"),
    raydium: RaydiumSnapshot | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Choose treasury, Raydium, or fail closed for one existing order."""

    policy.validate()
    timestamp = int(now or time.time())
    wallet = buyer_wallet.strip()
    order_id = str(order.get("order_id") or "").strip()
    expected_wallet = str(order.get("buyer_wallet") or "").strip()
    status = str(order.get("status") or "").strip().lower()
    required_iat = decimal_value(order.get("price"), "order_price")

    if not order_id or not wallet or wallet != expected_wallet:
        raise CheckoutRejected("order_buyer_mismatch")
    if status in TERMINAL_ORDER_STATES or bool(order.get("used")):
        raise CheckoutRejected("order_not_payable")
    if required_iat <= 0:
        raise CheckoutRejected("invalid_order_price")
    if timestamp - asset.observed_at > policy.oracle_max_age_seconds:
        raise CheckoutRejected("asset_oracle_stale")

    treasury_reasons: list[str] = []
    if not policy.treasury_enabled:
        treasury_reasons.append("treasury_disabled")
    if required_iat > policy.max_order_iat:
        treasury_reasons.append("order_cap_exceeded")
    if wallet_iat_today + required_iat > policy.wallet_daily_iat_cap:
        treasury_reasons.append("wallet_daily_cap_exceeded")
    if treasury_iat_today + required_iat > policy.treasury_daily_iat_cap:
        treasury_reasons.append("treasury_daily_cap_exceeded")
    if required_iat > policy.treasury_inventory_iat - treasury_iat_today:
        treasury_reasons.append("treasury_inventory_insufficient")
    if not policy.treasury_program_id or not policy.treasury_vault:
        treasury_reasons.append("treasury_onchain_configuration_missing")

    route: str | None = None
    input_amount: Decimal | None = None
    market_evidence: dict[str, Any] = {}
    if not treasury_reasons:
        gross_usd = required_iat * policy.iat_usd_reference_price
        input_amount = (
            gross_usd
            * (Decimal(10_000 + policy.treasury_spread_bps) / Decimal(10_000))
            / asset.usd_price
        )
        route = "treasury"

    raydium_reasons: list[str] = []
    if route is None:
        if not policy.raydium_enabled:
            raydium_reasons.append("raydium_disabled")
        if raydium is None:
            raydium_reasons.append("raydium_quote_unavailable")
        else:
            if timestamp - raydium.observed_at > policy.oracle_max_age_seconds:
                raydium_reasons.append("raydium_quote_stale")
            if raydium.pool_id not in policy.allowed_raydium_pools:
                raydium_reasons.append("raydium_pool_not_allowlisted")
            if raydium.price_impact_bps > policy.max_raydium_price_impact_bps:
                raydium_reasons.append("raydium_price_impact_exceeded")
            if raydium.pool_liquidity_usd < policy.min_raydium_liquidity_usd:
                raydium_reasons.append("raydium_liquidity_insufficient")
            if raydium.output_iat < required_iat:
                raydium_reasons.append("raydium_output_insufficient")
            if raydium.input_amount <= 0 or raydium.output_iat <= 0:
                raydium_reasons.append("raydium_quote_invalid")
            else:
                dex_iat_usd = (
                    raydium.input_amount * asset.usd_price / raydium.output_iat
                )
                deviation = _deviation_bps(
                    dex_iat_usd, policy.iat_usd_reference_price
                )
                market_evidence = {
                    "pool_id": raydium.pool_id,
                    "pool_liquidity_usd": str(raydium.pool_liquidity_usd),
                    "price_impact_bps": raydium.price_impact_bps,
                    "reference_deviation_bps": deviation,
                }
                if deviation > policy.max_reference_deviation_bps:
                    raydium_reasons.append("raydium_reference_deviation_exceeded")
        if not raydium_reasons and raydium is not None:
            route = "raydium"
            input_amount = raydium.input_amount

    if route is None or input_amount is None:
        raise CheckoutRejected(
            "no_safe_checkout_route",
            details={
                "treasury": treasury_reasons,
                "raydium": raydium_reasons,
            },
        )

    expires_at = timestamp + policy.quote_ttl_seconds
    intent = {
        "order_id": order_id,
        "buyer_wallet": wallet,
        "input_asset": asset.symbol,
        "input_mint": asset.mint,
        "input_amount_minor": _minor_units(input_amount, asset.decimals),
        "required_iat_minor": _minor_units(required_iat, IAT_DECIMALS),
        "iat_mint": IAT_TOKEN_ADDRESS,
        "route": route,
        "created_at": timestamp,
        "expires_at": expires_at,
    }
    return {
        "status": "quoted",
        "route": route,
        "order_id": order_id,
        "buyer_wallet": wallet,
        "input": {
            "asset": asset.symbol,
            "mint": asset.mint,
            "amount": str(input_amount.quantize(Decimal(1) / (Decimal(10) ** asset.decimals), rounding=ROUND_UP)),
            "amount_minor": intent["input_amount_minor"],
            "amount_semantics": "exact" if route == "treasury" else "maximum",
            "oracle": asset.oracle,
            "oracle_observed_at": asset.observed_at,
        },
        "output": {
            "asset": "IAT",
            "mint": IAT_TOKEN_ADDRESS,
            "amount": str(required_iat),
            "amount_minor": intent["required_iat_minor"],
            "destination": "order_settlement_escrow_only",
            "withdrawable_to_buyer": False,
        },
        "execution": {
            "network": "solana",
            "atomic": True,
            "custodial": False,
            "requires_buyer_wallet_signature": True,
            "server_signs_for_buyer": False,
            "treasury_program_id": policy.treasury_program_id if route == "treasury" else None,
            "treasury_vault": policy.treasury_vault if route == "treasury" else None,
        },
        "market_evidence": market_evidence,
        "created_at": timestamp,
        "expires_at": expires_at,
        "intent_hash": canonical_hash(intent),
        "protections": [
            "existing_order_only",
            "wallet_bound",
            "exact_output_to_order_escrow",
            "short_lived_quote",
            "no_buyer_iat_withdrawal",
            "daily_and_inventory_caps",
            "oracle_freshness",
            "fixed_mint_and_pool_allowlists",
        ],
    }
