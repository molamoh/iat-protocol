from typing import Dict, Any

SERVICE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "web_research": {
        "default_capability": "research",
        "preferred_adapter": "python",
    },
    "market_analysis": {
        "default_capability": "market_summary",
        "preferred_adapter": "python",
    },
    "translation": {
        "default_capability": "translation",
        "preferred_adapter": "python",
    },
    "code_review": {
        "default_capability": "code_review",
        "preferred_adapter": "python",
    },
}


def resolve_service(service: str) -> Dict[str, Any]:
    return dict(
        SERVICE_REGISTRY.get(
            str(service or "").lower(),
            {
                "default_capability": "echo",
                "preferred_adapter": "python",
            },
        )
    )
