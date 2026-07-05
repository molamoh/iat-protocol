from typing import Dict, Any, Callable

PYTHON_TASKS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}


def register_python_task(name: str):
    def decorator(func):
        PYTHON_TASKS[name] = func
        return func
    return decorator


def execute_python_task(name: str, execution_context: Dict[str, Any]):
    task = PYTHON_TASKS.get(name)

    if task is None:
        return {
            "status": "python_task_not_registered",
            "task": name,
        }

    return task(execution_context)
