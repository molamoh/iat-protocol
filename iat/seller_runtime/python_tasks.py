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


@register_python_task("summarize_stub")
def summarize(ctx):
    return {
        "status": "ok",
        "result": {
            "summary": f"Summary for: {ctx.get('task')}",
        },
    }


@register_python_task("market_summary_stub")
def market_summary_stub(ctx):
    task = ctx.get("task") or ""
    scope = ctx.get("scope") or {}

    return {
        "status": "ok",
        "result": {
            "summary": f"Market summary generated for: {task}",
            "scope": scope,
            "risk_notes": [
                "This is a safe Python runtime stub.",
                "Live market data adapter is not enabled yet."
            ],
            "confidence": 0.5,
        },
    }
