from typing import Any, Dict, List, Optional


ACTION_REGISTRY: Dict[str, Dict[str, Any]] = {
    "settlement_release": {
        "action_type": "settlement_release",
        "description": "Release a financial settlement through the protocol action layer.",
        "default_adapter": "dry_run",
        "allowed_adapters": ["dry_run"],
        "required_payload_fields": [
            "settlement_id",
            "order_id",
            "gross_amount_iat",
            "seller_payout_amount_iat",
            "protocol_commission_amount_iat",
            "winner_wallet",
            "onchain_settlement_enabled",
        ],
        "required_permissions": [
            "settlement.execute",
            "funds.release",
        ],
        "fallback_adapter": "dry_run",
        "status": "active",
        "version": "1.0.0",
    }
}


def list_registered_actions() -> List[str]:
    return sorted(ACTION_REGISTRY.keys())


def get_action_definition(action_type: str) -> Optional[Dict[str, Any]]:
    definition = ACTION_REGISTRY.get(str(action_type or ""))
    if not definition:
        return None
    return dict(definition)


def validate_action_request(action_request: Dict[str, Any]) -> Dict[str, Any]:
    action_request = action_request or {}
    action_type = action_request.get("action_type")

    definition = get_action_definition(action_type)

    if not definition:
        return {
            "valid": False,
            "reason": "action_type_not_registered",
            "action_type": action_type,
        }

    payload = action_request.get("payload") or {}
    missing_fields = []

    for field in definition.get("required_payload_fields", []):
        if field not in payload:
            missing_fields.append(field)

    if missing_fields:
        return {
            "valid": False,
            "reason": "missing_required_payload_fields",
            "action_type": action_type,
            "missing_fields": missing_fields,
            "definition": definition,
        }

    return {
        "valid": True,
        "reason": "action_request_valid",
        "action_type": action_type,
        "definition": definition,
    }


def resolve_adapter_for_action(action_request: Dict[str, Any]) -> Dict[str, Any]:
    validation = validate_action_request(action_request)

    if not validation.get("valid"):
        return {
            "status": "invalid_action_request",
            "reason": validation.get("reason"),
            "validation": validation,
            "adapter": None,
        }

    definition = validation.get("definition") or {}
    metadata = action_request.get("metadata") or {}

    requested_adapter = metadata.get("adapter") or metadata.get("execution_mode")
    allowed_adapters = definition.get("allowed_adapters") or []

    if requested_adapter in allowed_adapters:
        adapter = requested_adapter
    else:
        adapter = definition.get("default_adapter")

    if adapter not in allowed_adapters:
        return {
            "status": "adapter_not_allowed",
            "reason": "resolved_adapter_not_allowed_for_action",
            "adapter": adapter,
            "allowed_adapters": allowed_adapters,
            "validation": validation,
        }

    return {
        "status": "adapter_resolved",
        "reason": "adapter_resolved_for_action",
        "adapter": adapter,
        "validation": validation,
        "definition": definition,
    }
