from typing import Dict, Any
import time


ALLOWED_PYTHON_TASKS = {
    "echo",
    "transform",
    "summarize_stub",
}


def execute_python_adapter(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    task_type = (
        seller_agent.get("python_task")
        or seller_agent.get("task_type")
        or "echo"
    )

    if task_type not in ALLOWED_PYTHON_TASKS:
        return {
            "status": "python_task_not_allowed",
            "adapter": "python",
            "task_type": task_type,
        }

    started_at = int(time.time())

    if task_type == "echo":
        result = {
            "task": execution_context.get("task"),
            "scope": execution_context.get("scope"),
            "requested_format": execution_context.get("required_format"),
        }

    elif task_type == "transform":
        result = {
            "input": execution_context,
            "transformed": True,
            "format": execution_context.get("required_format"),
        }

    else:
        result = {
            "summary": "Python adapter V1 executed safe stub summarization.",
            "task": execution_context.get("task"),
        }

    return {
        "status": "ok",
        "adapter": "python",
        "execution_mode": "python_sandbox_stub",
        "started_at": started_at,
        "completed_at": int(time.time()),
        "result": result,
    }
