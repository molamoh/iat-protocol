"""Seller acquisition contracts, readiness analysis, and transparent economics."""

from __future__ import annotations

import os
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping


SELLER_INTERFACE_VERSION = "iat_seller_interface_v1"
_STEP = Decimal("0.000001")
_MAX_AMOUNT = Decimal("1000000000")


class SellerGrowthValidationError(ValueError):
    """A seller planning request violated a public contract."""


def _decimal(value: Any, *, name: str, maximum: Decimal = _MAX_AMOUNT) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SellerGrowthValidationError(f"{name}_must_be_decimal") from exc
    if not result.is_finite() or result < 0 or result > maximum:
        raise SellerGrowthValidationError(f"{name}_out_of_range")
    return result.quantize(_STEP, rounding=ROUND_HALF_UP)


def _rate(value: Any, *, name: str) -> Decimal:
    return _decimal(value, name=name, maximum=Decimal("1"))


def current_commission_rate() -> Decimal:
    """Mirror the production settlement rate without changing settlement policy."""
    try:
        configured = Decimal(os.getenv("IAT_PROTOCOL_COMMISSION_RATE", "0.10"))
    except InvalidOperation:
        configured = Decimal("0.10")
    return max(Decimal("0"), min(Decimal("0.50"), configured)).quantize(_STEP)


def build_seller_discovery() -> dict[str, Any]:
    return {
        "status": "ok",
        "interface": SELLER_INTERFACE_VERSION,
        "audience": ["ai_supplier", "software_vendor", "service_provider"],
        "value_proposition": {
            "buyer_access": "foundation-mediated demand from autonomous buyers",
            "integration": "HTTP, Python plugin, or IAT internal runtime",
            "settlement": "protocol-controlled atomic commission and payout",
            "trust": "portable execution evidence and bounded risk governance",
            "privacy": "buyer identity and raw prompts are hidden from sellers",
        },
        "journey": [
            {
                "step": "evaluate",
                "routes": [
                    "/seller/v1/readiness",
                    "/seller/v1/economics/estimate",
                    "/seller/v1/integration-contract",
                ],
                "account_required": False,
            },
            {
                "step": "register",
                "route": "/seller/register",
                "account_required": False,
            },
            {
                "step": "connect_runtime",
                "route": "/seller/register-agent",
                "seller_api_key_required": True,
            },
            {
                "step": "publish",
                "route": "/seller/catalog/items",
                "seller_api_key_required": True,
            },
            {
                "step": "operate",
                "routes": [
                    "/seller/dashboard",
                    "/seller/analytics",
                    "/seller/payouts",
                ],
                "seller_api_key_required": True,
            },
        ],
        "commercial_policy": build_commission_policy(),
        "differentiators": [
            "agent_native_machine_contracts",
            "foundation_mediated_buyer_privacy",
            "verifiable_execution_evidence",
            "explainable_supplier_selection",
            "atomic_commission_and_seller_payout",
            "autonomous_runtime_health_and_recovery",
        ],
    }


def build_commission_policy() -> dict[str, Any]:
    rate = current_commission_rate()
    return {
        "policy_version": "iat_commission_policy_v1",
        "currency": "IAT",
        "production_rate": str(rate),
        "production_rate_percent": str((rate * 100).quantize(Decimal("0.01"))),
        "maximum_protocol_rate": "0.500000",
        "basis": "successfully_settled_gross_order_amount",
        "charged_on_failed_orders": False,
        "charged_on_cancelled_orders": False,
        "charged_on_sandbox_orders": False,
        "seller_payout_formula": "gross_settled - protocol_commission",
        "atomic_split_supported": True,
        "notes": [
            "This document mirrors the active settlement configuration.",
            "It does not promise tax treatment, token value, or future pricing.",
            "Any future tier or incentive must be versioned before affecting settlement.",
        ],
    }


def estimate_seller_economics(
    *,
    unit_price: Any,
    monthly_completed_orders: int,
    refund_rate: Any = "0",
    variable_cost_per_order: Any = "0",
    commission_rate: Any | None = None,
) -> dict[str, Any]:
    price = _decimal(unit_price, name="unit_price")
    variable_cost = _decimal(variable_cost_per_order, name="variable_cost_per_order")
    refunds = _rate(refund_rate, name="refund_rate")
    try:
        orders = int(monthly_completed_orders)
    except (TypeError, ValueError) as exc:
        raise SellerGrowthValidationError("monthly_completed_orders_must_be_integer") from exc
    if isinstance(monthly_completed_orders, bool) or orders != monthly_completed_orders:
        raise SellerGrowthValidationError("monthly_completed_orders_must_be_integer")
    if not 0 <= orders <= 10_000_000:
        raise SellerGrowthValidationError("monthly_completed_orders_out_of_range")
    rate = current_commission_rate() if commission_rate is None else _rate(
        commission_rate,
        name="commission_rate",
    )

    gross = price * orders
    refunded = gross * refunds
    settled_gross = gross - refunded
    commission = settled_gross * rate
    payout = settled_gross - commission
    costs = variable_cost * orders
    contribution = payout - costs
    break_even_orders = None
    per_order_contribution = price * (Decimal("1") - refunds) * (Decimal("1") - rate)
    per_order_contribution -= variable_cost
    if per_order_contribution > 0:
        break_even_orders = 1

    return {
        "status": "ok",
        "interface": SELLER_INTERFACE_VERSION,
        "simulation_only": True,
        "currency": "IAT",
        "inputs": {
            "unit_price": str(price),
            "monthly_completed_orders": orders,
            "refund_rate": str(refunds),
            "variable_cost_per_order": str(variable_cost),
            "commission_rate": str(rate),
        },
        "monthly_projection": {
            "listed_gross": str(gross.quantize(_STEP)),
            "refunds": str(refunded.quantize(_STEP)),
            "settled_gross": str(settled_gross.quantize(_STEP)),
            "protocol_commission": str(commission.quantize(_STEP)),
            "seller_payout": str(payout.quantize(_STEP)),
            "seller_variable_costs": str(costs.quantize(_STEP)),
            "seller_contribution_after_commission": str(contribution.quantize(_STEP)),
        },
        "unit_economics": {
            "seller_payout_per_settled_order": str(
                (price * (Decimal("1") - rate)).quantize(_STEP)
            ),
            "contribution_per_expected_order": str(per_order_contribution.quantize(_STEP)),
            "economically_positive": per_order_contribution > 0,
            "minimum_orders_for_positive_month": break_even_orders,
        },
        "policy": build_commission_policy(),
    }


_READINESS_CHECKS = (
    ("identity", 10, ("seller_name", "wallet", "support_email")),
    ("commercial", 15, ("service", "unit_price", "currency", "refund_policy")),
    ("runtime", 25, ("runtime_adapter", "runtime_url", "health_endpoint")),
    ("capabilities", 15, ("capabilities", "input_schema", "output_schema")),
    ("reliability", 15, ("timeout_seconds", "capacity_per_day", "idempotency_supported")),
    ("security", 15, ("data_policy", "secret_handling", "incident_contact")),
    ("evidence", 5, ("evidence_types",)),
)


def evaluate_seller_readiness(profile: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(profile or {})
    sections = []
    missing: list[str] = []
    score = 0

    for section, weight, fields in _READINESS_CHECKS:
        present = [field for field in fields if _is_present(normalized.get(field))]
        absent = [field for field in fields if field not in present]
        section_score = round(weight * len(present) / len(fields), 2)
        score += section_score
        missing.extend(absent)
        sections.append(
            {
                "section": section,
                "weight": weight,
                "score": section_score,
                "ready": not absent,
                "present": present,
                "missing": absent,
            }
        )

    blockers = _readiness_blockers(normalized)
    score = round(max(0.0, score - (10.0 * len(blockers))), 2)
    if blockers or score < 70:
        level = "not_ready"
    elif score < 90:
        level = "ready_for_review"
    else:
        level = "integration_ready"

    return {
        "status": "ok",
        "interface": SELLER_INTERFACE_VERSION,
        "readiness": {
            "level": level,
            "score": score,
            "maximum_score": 100,
            "sections": sections,
            "missing_fields": missing,
            "blockers": blockers,
            "can_register": not any(
                blocker in {"wallet_required", "support_contact_required"}
                for blocker in blockers
            ),
            "can_become_buyer_routable": level == "integration_ready",
        },
        "next_actions": _next_actions(missing, blockers),
        "policy": {
            "assessment_creates_account": False,
            "assessment_calls_runtime": False,
            "assessment_changes_production_trust": False,
            "foundation_review_still_required": True,
        },
    }


def build_integration_contract(runtime_adapter: str = "http") -> dict[str, Any]:
    adapter = str(runtime_adapter or "http").strip().lower()
    if adapter not in {"http", "python", "internal"}:
        raise SellerGrowthValidationError("unsupported_runtime_adapter")
    contract = {
        "interface": SELLER_INTERFACE_VERSION,
        "runtime_adapter": adapter,
        "required_invariants": [
            "deterministic_request_validation",
            "bounded_execution_timeout",
            "idempotent_execution",
            "no_direct_buyer_contact",
            "no_raw_buyer_prompt_access",
            "structured_json_result",
            "secret_redaction",
        ],
        "execution_envelope": {
            "request": {
                "action_id": "string",
                "service": "string",
                "payload": "object",
                "constraints": "object",
                "deadline": "RFC3339 timestamp",
            },
            "response": {
                "status": "completed|failed|rejected",
                "result": "object|null",
                "evidence": "array",
                "error": "structured object|null",
            },
        },
        "health_contract": {
            "status_code": 200,
            "content_type": "application/json",
            "required_fields": ["status", "runtime_version", "capabilities"],
        },
        "security": {
            "https_required_in_production": True,
            "private_network_targets_rejected": True,
            "foundation_mediated": True,
            "buyer_data_minimized": True,
        },
    }
    if adapter == "http":
        contract["adapter_requirements"] = {
            "runtime_url_required": True,
            "health_endpoint_required": True,
            "request_signing": "planned",
        }
    elif adapter == "python":
        contract["adapter_requirements"] = {
            "registered_plugin_required": True,
            "network_access": "denied_by_default",
        }
    else:
        contract["adapter_requirements"] = {
            "foundation_approval_required": True,
            "external_registration": False,
        }
    return deepcopy(contract)


def _readiness_blockers(profile: Mapping[str, Any]) -> list[str]:
    blockers = []
    if not _is_present(profile.get("wallet")):
        blockers.append("wallet_required")
    if not _is_present(profile.get("support_email")):
        blockers.append("support_contact_required")
    adapter = str(profile.get("runtime_adapter") or "").lower()
    if adapter not in {"http", "python", "internal"}:
        blockers.append("supported_runtime_adapter_required")
    if adapter == "http":
        runtime_url = str(profile.get("runtime_url") or "")
        if not runtime_url.startswith("https://"):
            blockers.append("https_runtime_required")
    currency = str(profile.get("currency") or "").upper()
    if currency and currency != "IAT":
        blockers.append("unsupported_settlement_currency")
    return blockers


def _next_actions(missing: list[str], blockers: list[str]) -> list[dict[str, Any]]:
    actions = []
    for blocker in blockers:
        actions.append({"priority": "blocking", "action": f"resolve:{blocker}"})
    for field in missing:
        action = {"priority": "required", "action": f"provide:{field}"}
        if action not in actions:
            actions.append(action)
    if not actions:
        actions.append({"priority": "next", "action": "register_seller"})
    return actions


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True
