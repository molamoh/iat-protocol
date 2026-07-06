from typing import Dict, Any
import time

import iat.seller_runtime.python_plugins  # registers plugins
from iat.seller_runtime.plugin_registry import (
    get_plugin,
    find_plugin_by_capability,
)


def execute_python_adapter(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    started_at = int(time.time())

    plugin_name = (
        seller_agent.get("python_plugin")
        or seller_agent.get("python_task")
        or seller_agent.get("task_type")
    )

    plugin = None

    if plugin_name:
        plugin = get_plugin(plugin_name)

    if plugin is None:
        for capability in seller_agent.get("capabilities", []) or []:
            plugin = find_plugin_by_capability(capability)
            if plugin:
                break

    if plugin is None:
        return {
            "status": "python_plugin_not_found",
            "adapter": "python",
            "capabilities": seller_agent.get("capabilities", []),
        }

    runtime = plugin["handler"](execution_context)

    if runtime.get("status") != "ok":
        return {
            **runtime,
            "adapter": "python",
            "execution_mode": "python_plugin_runtime",
            "plugin": plugin.get("name"),
        }

    return {
        "status": "ok",
        "adapter": "python",
        "execution_mode": "python_plugin_runtime",
        "plugin": plugin.get("name"),
        "capability": plugin.get("capability"),
        "started_at": started_at,
        "completed_at": int(time.time()),
        "result": runtime.get("result"),
    }
