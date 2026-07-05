from typing import Dict, Any

ADAPTER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "python": {
        "priority": 100,
        "enabled": True,
    },
    "http": {
        "priority": 90,
        "enabled": True,
    },
    "internal": {
        "priority": 10,
        "enabled": True,
    },
}


def resolve_adapter(candidate: str) -> Dict[str, Any]:
    adapter = ADAPTER_REGISTRY.get(str(candidate or "").lower())

    if adapter and adapter.get("enabled"):
        return {
            "adapter": candidate.lower(),
            **adapter,
        }

    return {
        "adapter": "internal",
        "priority": 0,
        "enabled": True,
    }
