"""Idempotent settlement allocation after universal-checkout delivery."""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from solders.pubkey import Pubkey

from iat.api.db import (
    get_agent_db,
    get_settlement_by_order_id_db,
    record_settlement_db,
)


def _amount(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return max(parsed, Decimal("0"))


def _valid_wallet(value: Any) -> bool:
    try:
        Pubkey.from_string(str(value))
        return True
    except Exception:
        return False


def allocate_checkout_settlement(
    order: dict[str, Any],
    delivery_result: dict[str, Any],
) -> dict[str, Any]:
    """Create one pending settlement allocation per delivered order.

    This function never signs or broadcasts a transaction. Existing settlement
    governance remains the sole authority for an eventual escrow release.
    """
    order_id = str(order.get("order_id") or "").strip()
    if not order_id:
        return {"status": "blocked", "reason": "order_id_missing"}

    existing = get_settlement_by_order_id_db(order_id)
    if existing:
        return {
            "status": "settlement_already_recorded",
            "settlement_id": existing.get("settlement_id"),
            "order_id": order_id,
            "idempotent": True,
        }

    best = (
        delivery_result.get("best_result")
        if isinstance(delivery_result, dict)
        else None
    ) or {}
    winner_id = (
        best.get("agent_id")
        or order.get("seller_id")
        or order.get("selected_agent_id")
        or order.get("locked_agent_id")
    )
    agent = get_agent_db(winner_id) if winner_id else None
    winner_wallet = (
        best.get("wallet")
        or order.get("actual_agent_wallet")
        or (agent or {}).get("wallet")
        or order.get("seller_wallet")
    )

    gross = _amount(order.get("price"))
    try:
        commission_rate = Decimal(
            os.getenv("IAT_PROTOCOL_COMMISSION_RATE", "0.10")
        )
    except InvalidOperation:
        commission_rate = Decimal("0.10")
    commission_rate = min(max(commission_rate, Decimal("0")), Decimal("0.50"))
    commission = (gross * commission_rate).quantize(
        Decimal("0.000001"), rounding=ROUND_DOWN
    )
    payout = gross - commission

    if not winner_id:
        payment_status = "blocked_no_winner"
        reason = "winner_agent_missing"
    elif not _valid_wallet(winner_wallet):
        payment_status = "blocked_invalid_winner_wallet"
        reason = "winner_wallet_invalid"
    elif gross <= 0:
        payment_status = "no_payment_due"
        reason = "zero_amount_order"
    else:
        payment_status = "pending_escrow_release"
        reason = "delivery_recorded_waiting_for_settlement_governance"

    payload = {
        "settlement_type": "universal_checkout_delivery_allocation",
        "settlement_source": "universal_checkout",
        "order_id": order_id,
        "winner_id": winner_id,
        "winner_wallet": winner_wallet,
        "gross_amount_iat": str(gross),
        "protocol_commission_rate": str(commission_rate),
        "protocol_commission_amount_iat": str(commission),
        "seller_payout_amount_iat": str(payout),
        "winner_payment_status": payment_status,
        "reason": reason,
        "protocol_treasury_wallet": os.getenv("IAT_PROTOCOL_TREASURY_WALLET"),
        "delivery_status": delivery_result.get("status"),
        "release_policy": {
            "allocation_is_not_release": True,
            "seller_cannot_self_release": True,
            "protocol_governance_required": True,
            "onchain_broadcast_performed": False,
        },
    }
    record = record_settlement_db(order_id, payload)
    return record or {
        "status": "blocked",
        "reason": "settlement_record_not_created",
        "order_id": order_id,
    }
