from typing import Dict

CAPABILITY_TASK_MAP: Dict[str, str] = {
    "market_summary": "market_summary_stub",
    "research": "summarize_stub",
    "echo": "echo",
}


def resolve_python_task(capabilities):
    capabilities = capabilities or []

    for capability in capabilities:
        task = CAPABILITY_TASK_MAP.get(str(capability).lower())
        if task:
            return task

    return "echo"
