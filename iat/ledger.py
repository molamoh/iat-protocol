"""Exact monetary primitives and double-entry invariants."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping


LEDGER_VERSION = "iat_double_entry_ledger_v1"
IAT_DECIMALS = 8
IAT_SCALE = 10**IAT_DECIMALS
MAX_IAT_MINOR = (2**63) - 1


class LedgerValidationError(ValueError):
    """A monetary value or journal violates a ledger invariant."""


def iat_to_minor(value: Any) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LedgerValidationError("amount_must_be_decimal") from exc
    if not amount.is_finite() or amount < 0:
        raise LedgerValidationError("amount_out_of_range")
    scaled = (amount * IAT_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    result = int(scaled)
    if result > MAX_IAT_MINOR:
        raise LedgerValidationError("amount_out_of_range")
    return result


def minor_to_iat(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LedgerValidationError("minor_amount_must_be_integer")
    if abs(value) > MAX_IAT_MINOR:
        raise LedgerValidationError("minor_amount_out_of_range")
    return f"{Decimal(value) / IAT_SCALE:.8f}"


def canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_journal(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    normalized = list(entries)
    if len(normalized) < 2:
        raise LedgerValidationError("journal_requires_at_least_two_entries")

    totals: dict[str, dict[str, int]] = {}
    for entry in normalized:
        direction = str(entry.get("direction") or "").lower()
        currency = str(entry.get("currency") or "").upper()
        amount_minor = entry.get("amount_minor")
        account_id = str(entry.get("account_id") or "").strip()
        if direction not in {"debit", "credit"}:
            raise LedgerValidationError("entry_direction_invalid")
        if currency != "IAT":
            raise LedgerValidationError("entry_currency_invalid")
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
            raise LedgerValidationError("entry_amount_must_be_integer")
        if amount_minor <= 0 or amount_minor > MAX_IAT_MINOR:
            raise LedgerValidationError("entry_amount_out_of_range")
        if not account_id:
            raise LedgerValidationError("entry_account_required")
        currency_totals = totals.setdefault(currency, {"debit": 0, "credit": 0})
        currency_totals[direction] += amount_minor

    imbalances = {
        currency: values["debit"] - values["credit"]
        for currency, values in totals.items()
        if values["debit"] != values["credit"]
    }
    if imbalances:
        raise LedgerValidationError("journal_not_balanced")

    return {
        "status": "balanced",
        "ledger": LEDGER_VERSION,
        "entry_count": len(normalized),
        "currencies": totals,
        "imbalances": {},
    }


def build_settlement_allocation_journal(
    *,
    settlement_id: str,
    gross_amount_iat: Any,
    protocol_commission_amount_iat: Any,
    seller_payout_amount_iat: Any,
    seller_id: str | None,
) -> dict[str, Any]:
    gross = iat_to_minor(gross_amount_iat)
    commission = iat_to_minor(protocol_commission_amount_iat)
    payout = iat_to_minor(seller_payout_amount_iat)
    if gross <= 0:
        raise LedgerValidationError("settlement_gross_must_be_positive")
    if commission + payout != gross:
        raise LedgerValidationError("settlement_split_does_not_equal_gross")

    entries = [
        {
            "account_id": "iat:settlement_clearing",
            "direction": "debit",
            "amount_minor": gross,
            "currency": "IAT",
        }
    ]
    if payout:
        entries.append(
            {
                "account_id": f"iat:seller_payable:{seller_id or 'unknown'}",
                "direction": "credit",
                "amount_minor": payout,
                "currency": "IAT",
            }
        )
    if commission:
        entries.append(
            {
                "account_id": "iat:protocol_commission_revenue",
                "direction": "credit",
                "amount_minor": commission,
                "currency": "IAT",
            }
        )
    invariant = validate_journal(entries)
    payload = {
        "ledger_version": LEDGER_VERSION,
        "event_type": "settlement_allocated",
        "settlement_id": settlement_id,
        "gross_amount_minor": gross,
        "commission_amount_minor": commission,
        "seller_payout_amount_minor": payout,
        "seller_id": seller_id,
    }
    return {
        "idempotency_key": f"settlement-allocation:{settlement_id}:v1",
        "event_type": "settlement_allocated",
        "payload": payload,
        "payload_hash": canonical_hash(payload),
        "entries": entries,
        "invariant": invariant,
    }
