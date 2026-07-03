from typing import Any, Dict, List

from iat.action_engine.context import normalize_action_context, validate_action_context
from iat.action_engine.execution_pipeline import get_execution_pipeline
from iat.action_engine.pipeline_registry import get_pipeline_stage


def execute_pipeline(action_context: Dict[str, Any]) -> Dict[str, Any]:
    validation = validate_action_context(action_context)

    if not validation.get("valid"):
        return {
            "status": "pipeline_rejected",
            "reason": validation.get("reason"),
            "validation": validation,
            "executed": False,
        }

    ctx = normalize_action_context(validation.get("context"))
    pipeline = get_execution_pipeline(ctx.get("action_type"))

    stage_results: List[Dict[str, Any]] = []
    final_stage_result: Dict[str, Any] = {}

    for stage_name in pipeline:
        stage_runner = get_pipeline_stage(stage_name)

        if not stage_runner:
            result = {
                "stage": stage_name,
                "status": "failed",
                "reason": "pipeline_stage_not_registered",
                "continue_pipeline": False,
            }
        else:
            result = stage_runner(ctx)

        stage_results.append(result)
        final_stage_result = result

        if not result.get("continue_pipeline"):
            return {
                "status": "pipeline_stopped",
                "reason": result.get("reason"),
                "pipeline": pipeline,
                "stage_results": stage_results,
                "final_stage": final_stage_result,
                "action_context": ctx,
                "executed": False,
            }

    final_result = final_stage_result.get("result") or {}

    if isinstance(final_result, dict):
        final_result["pipeline"] = {
            "status": "completed",
            "pipeline": pipeline,
            "stage_results": stage_results,
        }
        final_result["action_context"] = ctx
        final_result["executed"] = final_result.get("status") not in (
            "action_rejected",
            "unsupported_adapter",
        )
        return final_result

    return {
        "status": "pipeline_completed",
        "reason": "pipeline_completed_without_structured_final_result",
        "pipeline": pipeline,
        "stage_results": stage_results,
        "action_context": ctx,
        "executed": True,
    }
