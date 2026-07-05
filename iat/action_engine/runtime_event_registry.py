from typing import Dict, Any

_RUNTIME_EVENTS = {

    "WorkerSelected": {
        "category": "worker",
        "severity": "info",
        "consumers": ["metrics"],
    },

    "WorkerBusy": {
        "category": "worker",
        "severity": "info",
        "consumers": ["metrics"],
    },

    "WorkerExecutionCompleted": {
        "category": "worker",
        "severity": "info",
        "consumers": ["metrics"],
    },

    "WorkerExecutionFailed": {
        "category": "worker",
        "severity": "warning",
        "consumers": [
            "metrics",
            "risk",
            "governance",
        ],
    },

    "ActionQueued": {
        "category": "action",
        "severity": "info",
        "consumers": ["metrics"],
    },

    "ActionClaimCreated": {
        "category": "claim",
        "severity": "info",
        "consumers": ["metrics"],
    },

    "ActionClaimReleased": {
        "category": "claim",
        "severity": "info",
        "consumers": ["metrics"],
    },

    "RuntimeSupervisorCycleCompleted": {
        "category": "runtime",
        "severity": "info",
        "consumers": ["metrics"],
    },
}


def get_runtime_event_definition(event_type: str) -> Dict[str, Any]:
    return _RUNTIME_EVENTS.get(
        event_type,
        {
            "category": "other",
            "severity": "info",
            "consumers": [],
        },
    )


def inspect_runtime_event_registry():
    return {
        "status": "ok",
        "count": len(_RUNTIME_EVENTS),
        "events": sorted(_RUNTIME_EVENTS.keys()),
    }
