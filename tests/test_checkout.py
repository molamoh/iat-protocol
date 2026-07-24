from decimal import Decimal

import pytest

from iat.checkout import (
    AssetSnapshot,
    CheckoutPolicy,
    CheckoutRejected,
    RaydiumSnapshot,
    quote_hybrid_checkout,
)


NOW = 2_000_000_000


def order(**overrides):
    value = {
        "order_id": "ord_123",
        "buyer_wallet": "Buyer111111111111111111111111111111111",
        "price": "10",
        "status": "created",
        "used": False,
    }
    value.update(overrides)
    return value


def asset(**overrides):
    value = {
        "mint": "USDC1111111111111111111111111111111111",
        "decimals": 6,
        "usd_price": "1",
        "oracle": "pyth",
        "observed_at": NOW - 5,
    }
    value.update(overrides)
    return AssetSnapshot.from_mapping("USDC", value)


def policy(**overrides):
    values = {
        "treasury_enabled": True,
        "raydium_enabled": True,
        "treasury_inventory_iat": Decimal("500"),
        "iat_usd_reference_price": Decimal("0.25"),
        "treasury_program_id": "IATCheckout11111111111111111111111111111",
        "treasury_vault": "Treasury1111111111111111111111111111111",
        "allowed_raydium_pools": ("pool-approved",),
    }
    values.update(overrides)
    return CheckoutPolicy(**values)


def raydium(**overrides):
    values = {
        "input_amount": "2.6",
        "output_iat": "10",
        "price_impact_bps": 120,
        "pool_liquidity_usd": "25000",
        "pool_id": "pool-approved",
        "observed_at": NOW - 3,
    }
    values.update(overrides)
    return RaydiumSnapshot.from_mapping(values)


def quote(**overrides):
    values = {
        "order": order(),
        "buyer_wallet": order()["buyer_wallet"],
        "asset": asset(),
        "policy": policy(),
        "now": NOW,
    }
    values.update(overrides)
    return quote_hybrid_checkout(**values)


def test_treasury_route_is_order_bound_and_never_withdrawable():
    result = quote()

    assert result["route"] == "treasury"
    assert result["input"]["amount"] == "2.512500"
    assert result["output"]["amount"] == "10"
    assert result["output"]["destination"] == "order_settlement_escrow_only"
    assert result["output"]["withdrawable_to_buyer"] is False
    assert result["execution"]["requires_buyer_wallet_signature"] is True
    assert len(result["intent_hash"]) == 64


def test_treasury_caps_cannot_be_bypassed():
    with pytest.raises(CheckoutRejected) as rejected:
        quote(
            wallet_iat_today=Decimal("245"),
            policy=policy(raydium_enabled=False),
        )

    assert rejected.value.code == "no_safe_checkout_route"
    assert "wallet_daily_cap_exceeded" in rejected.value.details["treasury"]


def test_raydium_is_only_fallback_and_requires_safe_market():
    result = quote(
        policy=policy(treasury_inventory_iat=Decimal("5")),
        raydium=raydium(),
    )

    assert result["route"] == "raydium"
    assert result["input"]["amount"] == "2.600000"
    assert result["market_evidence"]["pool_id"] == "pool-approved"


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        ({"pool_liquidity_usd": "80"}, "raydium_liquidity_insufficient"),
        ({"price_impact_bps": 900}, "raydium_price_impact_exceeded"),
        ({"pool_id": "attacker-pool"}, "raydium_pool_not_allowlisted"),
        ({"input_amount": "5"}, "raydium_reference_deviation_exceeded"),
        ({"observed_at": NOW - 500}, "raydium_quote_stale"),
    ],
)
def test_unsafe_raydium_market_fails_closed(snapshot, reason):
    with pytest.raises(CheckoutRejected) as rejected:
        quote(
            policy=policy(treasury_enabled=False),
            raydium=raydium(**snapshot),
        )

    assert rejected.value.code == "no_safe_checkout_route"
    assert reason in rejected.value.details["raydium"]


def test_stale_oracle_and_wallet_mismatch_are_rejected_before_routing():
    with pytest.raises(CheckoutRejected, match="asset_oracle_stale"):
        quote(asset=asset(observed_at=NOW - 500))

    with pytest.raises(CheckoutRejected, match="order_buyer_mismatch"):
        quote(buyer_wallet="Attacker111111111111111111111111111111")


@pytest.mark.parametrize("status", ["delivered", "settled", "refunded", "cancelled"])
def test_terminal_order_cannot_receive_quote(status):
    with pytest.raises(CheckoutRejected, match="order_not_payable"):
        quote(order=order(status=status))


def test_quote_hash_is_deterministic_and_expiration_is_bounded():
    first = quote()
    second = quote()

    assert first["intent_hash"] == second["intent_hash"]
    assert first["expires_at"] - first["created_at"] == 60
