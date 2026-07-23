from typing import Any, Dict, Iterable, List, Optional, Set


DEPENDENCY_RESOLVER_VERSION = "iat_dependency_resolver_v1"


def _normalize_ids(values: Optional[Iterable[Any]]) -> List[str]:
    if values is None:
        return []

    if isinstance(values, str):
        values = [values]

    if not isinstance(values, (list, tuple, set)):
        return []

    normalized: List[str] = []
    seen: Set[str] = set()

    for value in values:
        item = str(value or "").strip()

        if not item or item in seen:
            continue

        normalized.append(item)
        seen.add(item)

    return normalized


def get_action_dependencies(
    action_context: Dict[str, Any],
) -> List[str]:
    action_context = action_context or {}
    orchestration = action_context.get("orchestration") or {}

    return _normalize_ids(
        orchestration.get(
            "depends_on",
            action_context.get("depends_on"),
        )
    )


def resolve_action_dependencies(
    action_context: Dict[str, Any],
    *,
    completed_action_ids: Optional[Iterable[Any]] = None,
    failed_action_ids: Optional[Iterable[Any]] = None,
    known_action_ids: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    action_context = action_context or {}

    action_id = str(
        action_context.get("action_id") or ""
    ).strip()

    dependencies = get_action_dependencies(action_context)

    completed = set(_normalize_ids(completed_action_ids))
    failed = set(_normalize_ids(failed_action_ids))

    known = None
    if known_action_ids is not None:
        known = set(_normalize_ids(known_action_ids))

    if action_id and action_id in dependencies:
        return {
            "status": "dependency_invalid",
            "reason": "action_cannot_depend_on_itself",
            "resolver": DEPENDENCY_RESOLVER_VERSION,
            "action_id": action_id,
            "dependencies": dependencies,
            "dependency_count": len(dependencies),
            "ready": False,
            "blocked": True,
            "failed": True,
            "completed_dependencies": [],
            "pending_dependencies": [],
            "failed_dependencies": [],
            "missing_dependencies": [],
        }

    completed_dependencies = [
        dependency
        for dependency in dependencies
        if dependency in completed
    ]

    failed_dependencies = [
        dependency
        for dependency in dependencies
        if dependency in failed
    ]

    missing_dependencies = []

    if known is not None:
        missing_dependencies = [
            dependency
            for dependency in dependencies
            if dependency not in known
            and dependency not in completed
            and dependency not in failed
        ]

    pending_dependencies = [
        dependency
        for dependency in dependencies
        if dependency not in completed
        and dependency not in failed
        and dependency not in missing_dependencies
    ]

    if failed_dependencies:
        status = "dependency_failed"
        reason = "one_or_more_dependencies_failed"
        ready = False
        blocked = True
        dependency_failure = True

    elif missing_dependencies:
        status = "dependency_missing"
        reason = "one_or_more_dependencies_unknown"
        ready = False
        blocked = True
        dependency_failure = False

    elif pending_dependencies:
        status = "dependency_pending"
        reason = "dependencies_not_completed"
        ready = False
        blocked = True
        dependency_failure = False

    else:
        status = "dependency_ready"
        reason = (
            "all_dependencies_completed"
            if dependencies
            else "action_has_no_dependencies"
        )
        ready = True
        blocked = False
        dependency_failure = False

    return {
        "status": status,
        "reason": reason,
        "resolver": DEPENDENCY_RESOLVER_VERSION,
        "action_id": action_id,
        "dependencies": dependencies,
        "dependency_count": len(dependencies),
        "ready": ready,
        "blocked": blocked,
        "failed": dependency_failure,
        "completed_dependencies": completed_dependencies,
        "pending_dependencies": pending_dependencies,
        "failed_dependencies": failed_dependencies,
        "missing_dependencies": missing_dependencies,
    }


def detect_dependency_cycles(
    action_contexts: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    graph: Dict[str, List[str]] = {}

    for context in action_contexts or []:
        if not isinstance(context, dict):
            continue

        action_id = str(
            context.get("action_id") or ""
        ).strip()

        if not action_id:
            continue

        graph[action_id] = get_action_dependencies(context)

    visiting: Set[str] = set()
    visited: Set[str] = set()
    stack: List[str] = []
    cycles: List[List[str]] = []
    cycle_signatures: Set[tuple] = set()

    def visit(node: str) -> None:
        if node in visited:
            return

        if node in visiting:
            try:
                start = stack.index(node)
                cycle = stack[start:] + [node]
            except ValueError:
                cycle = [node, node]

            signature = tuple(cycle)

            if signature not in cycle_signatures:
                cycles.append(cycle)
                cycle_signatures.add(signature)

            return

        visiting.add(node)
        stack.append(node)

        for dependency in graph.get(node, []):
            if dependency in graph:
                visit(dependency)

        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for action_id in graph:
        visit(action_id)

    return {
        "status": (
            "dependency_cycles_detected"
            if cycles
            else "dependency_graph_valid"
        ),
        "reason": (
            "dependency_graph_contains_cycles"
            if cycles
            else "dependency_graph_is_acyclic"
        ),
        "resolver": DEPENDENCY_RESOLVER_VERSION,
        "action_count": len(graph),
        "cycle_count": len(cycles),
        "cycles": cycles,
        "valid": not cycles,
    }


def inspect_dependency_resolver() -> Dict[str, Any]:
    return {
        "status": "ok",
        "resolver": DEPENDENCY_RESOLVER_VERSION,
        "capabilities": {
            "dependency_normalization": True,
            "dependency_readiness": True,
            "missing_dependency_detection": True,
            "failed_dependency_detection": True,
            "cycle_detection": True,
            "database_integration": False,
            "queue_integration": False,
        },
    }
