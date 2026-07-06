from typing import Dict, Any

from iat.seller_runtime.service_registry import resolve_service
from iat.seller_runtime.adapter_registry import resolve_adapter
from iat.seller_runtime.plugin_registry import find_plugin_by_capability
from iat.seller_runtime.runtime_scoring import compute_runtime_score
import iat.seller_runtime.python_plugins  # registers plugins


def build_virtual_runtime_agent(
    service: str,
    execution_context: Dict[str, Any],
) -> Dict[str, Any]:
    resolved_service = resolve_service(service)

    capability = resolved_service.get("default_capability")
    adapter = resolve_adapter(resolved_service.get("preferred_adapter"))

    plugin = None
    if adapter.get("adapter") == "python":
        plugin = find_plugin_by_capability(capability)

    agent = {
        "seller_agent_id": f"virtual_runtime_{service}",
        "agent_id": f"virtual_runtime_{service}",
        "seller_id": "iat_foundation_virtual_runtime",
        "service": service,
        "runtime_adapter": adapter.get("adapter"),
        "capabilities": [capability],
        "specialties": [service],
        "success_rate": 1.0,
        "reputation": 1.0,
        "governance_score": 100,
        "runtime_health_score": 100,
        "risk_score": 0,
        "trust_score": 100,
        "metadata": {
            "virtual": True,
            "managed_by": "iat_foundation",
            "source": "runtime_resolver",
        },
    }

    if plugin:
        agent["python_plugin"] = plugin.get("name")

    agent["runtime_score"] = compute_runtime_score(agent)

    return agent


def resolve_seller_runtime_agent(
    service: str,
    execution_context: Dict[str, Any],
    selected_agent: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if selected_agent:
        selected_agent["runtime_score"] = compute_runtime_score(selected_agent)

        return {
            "status": "resolved",
            "source": "db_seller_agent",
            "agent": selected_agent,
        }

    return {
        "status": "resolved",
        "source": "virtual_runtime_agent",
        "agent": build_virtual_runtime_agent(
            service,
            execution_context,
        ),
    }
