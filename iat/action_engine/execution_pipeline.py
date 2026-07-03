from typing import Dict, List


DEFAULT_EXECUTION_PIPELINE: List[str] = [
    "scheduler",
    "dispatcher",
    "router",
]


ACTION_PIPELINES: Dict[str, List[str]] = {
    "settlement_release": DEFAULT_EXECUTION_PIPELINE,
}


def get_execution_pipeline(action_type: str) -> List[str]:
    return list(
        ACTION_PIPELINES.get(
            str(action_type or ""),
            DEFAULT_EXECUTION_PIPELINE,
        )
    )
