from typing import Dict, Any
import time

from iat.seller_runtime.python_registry import execute_python_task
from iat.seller_runtime.capability_registry import resolve_python_task
import iat.seller_runtime.python_tasks  # registers tasks


def execute_python_adapter(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    task_type = (
        seller_agent.get("python_task")
        or seller_agent.get("task_type")
    )

    if not task_type:
        task_type = resolve_python_task(
            seller_agent.get("capabilities", [])
        )

    started_at = int(time.time())

    runtime = execute_python_task(
        task_type,
        execution_context,
    )

    if runtime.get("status") != "ok":
        return {
            **runtime,
            "adapter": "python",
            "execution_mode": "python_registry",
        }

    return {
        "status": "ok",
        "adapter": "python",
        "execution_mode": "python_registry",
        "started_at": started_at,
        "completed_at": int(time.time()),
        "result": runtime.get("result"),
    }
