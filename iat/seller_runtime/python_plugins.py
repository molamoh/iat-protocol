from iat.seller_runtime.plugin_registry import register_plugin


@register_plugin(
    name="research_summary_v1",
    capability="research",
    adapter="python",
    priority=90,
)
def research_summary_plugin(ctx):
    task = str(ctx.get("task") or "")
    scope = ctx.get("scope") or {}

    return {
        "status": "ok",
        "result": {
            "summary": "Foundation-safe research summary generated.",
            "key_points": [
                f"Requested research task: {task}" if task else "No task provided.",
                f"Scope constraints: {scope}" if scope else "No scope constraints.",
            ],
            "scope": scope,
            "confidence": 0.6,
        },
    }


@register_plugin(
    name="market_summary_v1",
    capability="market_summary",
    adapter="python",
    priority=100,
)
def market_summary_plugin(ctx):
    task = str(ctx.get("task") or "")
    scope = ctx.get("scope") or {}

    return {
        "status": "ok",
        "result": {
            "summary": "Foundation-safe market summary generated.",
            "analysis_points": [
                f"Asset focus: {scope.get('asset')}" if isinstance(scope, dict) and scope.get("asset") else "Asset focus not specified.",
                f"Time horizon: {scope.get('horizon')}" if isinstance(scope, dict) and scope.get("horizon") else "Time horizon not specified.",
                f"Requested analysis: {task}" if task else "No specific analysis request.",
            ],
            "risk_notes": [
                "No live market feed was used in this Python plugin.",
                "Final buyer delivery must remain Foundation-verified.",
            ],
            "scope": scope,
            "confidence": 0.65,
        },
    }
