from typing import Dict, Any
import time
import uuid


def build_runtime_audit(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
    result: Dict[str, Any],
):
    return {
        "audit_id": str(uuid.uuid4()),
        "created_at": int(time.time()),
        "runtime": "iat_seller_runtime_v1",
        "seller_agent_id": seller_agent.get("seller_agent_id"),
        "agent_id": seller_agent.get("agent_id"),
        "seller_id": seller_agent.get("seller_id"),
        "service": execution_context.get("service") or seller_agent.get("service"),
        "adapter": seller_agent.get("runtime_adapter"),
        "status": result.get("status"),
        "execution_mode": result.get("execution_mode"),
        "policy": {
            "buyer_data_stripped": execution_context.get("buyer_data_stripped"),
            "foundation_mediated": execution_context.get("foundation_mediated"),
        },
        "trust": result.get("runtime_trust"),
        "governance": result.get("governance_policy"),
    }
