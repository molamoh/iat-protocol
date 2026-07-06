from typing import Dict, Any, Callable

PLUGIN_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_plugin(
    name: str,
    capability: str,
    adapter: str = "python",
    priority: int = 50,
):
    def decorator(func: Callable[[Dict[str, Any]], Dict[str, Any]]):
        PLUGIN_REGISTRY[name] = {
            "name": name,
            "capability": capability,
            "adapter": adapter,
            "priority": priority,
            "handler": func,
        }
        return func
    return decorator


def get_plugin(name: str):
    return PLUGIN_REGISTRY.get(str(name or ""))


def find_plugin_by_capability(capability: str):
    capability = str(capability or "").lower()

    candidates = [
        plugin
        for plugin in PLUGIN_REGISTRY.values()
        if str(plugin.get("capability") or "").lower() == capability
    ]

    if not candidates:
        return None

    candidates.sort(key=lambda p: p.get("priority", 0), reverse=True)
    return candidates[0]
