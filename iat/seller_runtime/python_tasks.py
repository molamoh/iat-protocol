from iat.seller_runtime.python_registry import register_python_task


@register_python_task("echo")
def task_echo(ctx):
    return {
        "status": "ok",
        "result": {
            "task": ctx.get("task"),
            "scope": ctx.get("scope"),
            "requested_format": ctx.get("required_format"),
        },
    }


@register_python_task("research_summary_v1")
def research_summary_v1(ctx):
    task = str(ctx.get("task") or "")
    scope = ctx.get("scope") or {}

    key_points = []

    if task:
        key_points.append(f"Requested research task: {task}")

    if isinstance(scope, dict) and scope:
        key_points.append(f"Scope constraints: {scope}")

    if not key_points:
        key_points.append("No detailed task or scope was provided.")

    return {
        "status": "ok",
        "result": {
            "summary": "Foundation-safe research summary generated.",
            "key_points": key_points,
            "scope": scope,
            "confidence": 0.6,
        },
    }


@register_python_task("market_summary_v1")
def market_summary_v1(ctx):
    task = str(ctx.get("task") or "")
    scope = ctx.get("scope") or {}

    asset = None
    horizon = None

    if isinstance(scope, dict):
        asset = scope.get("asset")
        horizon = scope.get("horizon")

    summary_parts = []

    if asset:
        summary_parts.append(f"Asset focus: {asset}")

    if horizon:
        summary_parts.append(f"Time horizon: {horizon}")

    if task:
        summary_parts.append(f"Requested analysis: {task}")

    if not summary_parts:
        summary_parts.append("Generic market analysis requested.")

    return {
        "status": "ok",
        "result": {
            "summary": "Foundation-safe market summary generated.",
            "analysis_points": summary_parts,
            "risk_notes": [
                "No live market feed was used in this Python task.",
                "Final buyer delivery must remain Foundation-verified.",
            ],
            "scope": scope,
            "confidence": 0.65,
        },
    }
