from typing import Dict, Any

CAPABILITY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "market_summary": {
        "python_task": "market_summary_stub",
        "priority": 100,
    },
    "research": {
        "python_task": "research_summary_v1",
        "priority": 90,
    },
    "echo": {
        "python_task": "echo",
        "priority": 1,
    },
}


def resolve_capability(capabilities):
    capabilities = capabilities or []

    best = None

    for capability in capabilities:
        item = CAPABILITY_REGISTRY.get(str(capability).lower())

        if not item:
            continue

        if best is None or item["priority"] > best["priority"]:
            best = item

    if best:
        return dict(best)

    return {
        "python_task": "echo",
        "priority": 0,
    }


def resolve_python_task(capabilities):
    return resolve_capability(capabilities)["python_task"]
