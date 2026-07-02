from iat.action_engine.models import build_action_request
from iat.action_engine.router import route_action


def execute_action(
    action_type,
    action_scope,
    payload=None,
    metadata=None,
):
    action_request = build_action_request(
        action_type=action_type,
        action_scope=action_scope,
        payload=payload or {},
        metadata=metadata or {},
    )

    return route_action(action_request)
