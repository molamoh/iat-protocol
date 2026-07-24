"""Admin API for the governed autonomous growth engine."""

from __future__ import annotations

from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from iat.growth import (
    GrowthValidationError,
    apply_recommendation,
    approve_action,
    campaign_analytics,
    create_campaign,
    discover_from_feed,
    execute_action,
    generate_campaign_recommendation,
    growth_dashboard,
    list_actions,
    list_campaigns,
    list_growth_events,
    list_prospects,
    list_recommendations,
    list_responses,
    list_suppressions,
    propose_action,
    qualify_prospect,
    record_conversion,
    retry_action,
    rollback_recommendation,
    run_growth_cycle,
    set_campaign_status,
    suppress_prospect,
    upsert_prospect,
)


class _StrictAdminModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProspectRequest(_StrictAdminModel):
    url: str = Field(min_length=8, max_length=2_000)
    name: str = Field(default="", max_length=200)
    segment: Literal[
        "ai_agent", "agent_platform", "marketplace", "framework", "seller", "unknown"
    ] = "unknown"
    source: str = Field(default="manual", min_length=2, max_length=120)
    metadata: dict = Field(default_factory=dict)


class CampaignRequest(_StrictAdminModel):
    name: str = Field(min_length=3, max_length=200)
    target_segment: Literal[
        "ai_agent", "agent_platform", "marketplace", "framework", "seller", "unknown"
    ] = "unknown"
    min_score: float = Field(default=60, ge=0, le=100)
    daily_action_limit: int = Field(default=25, ge=1, le=1_000)
    policy: dict = Field(default_factory=dict)


class CampaignStatusRequest(_StrictAdminModel):
    status: Literal["draft", "active", "paused", "completed"]


class ActionProposalRequest(_StrictAdminModel):
    prospect_id: str = Field(min_length=10, max_length=100)
    campaign_id: str = Field(min_length=10, max_length=100)


class ActionApprovalRequest(_StrictAdminModel):
    approved_by: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=5, max_length=500)


class ConversionRequest(_StrictAdminModel):
    conversion_type: str = Field(min_length=3, max_length=80)
    value: float = Field(default=0, ge=0)
    metadata: dict = Field(default_factory=dict)


class DiscoveryFeedRequest(_StrictAdminModel):
    feed_url: str = Field(min_length=8, max_length=2_000)


class SuppressionRequest(_StrictAdminModel):
    prospect_id: str | None = Field(default=None, max_length=100)
    domain: str | None = Field(default=None, max_length=253)
    reason: str = Field(min_length=3, max_length=500)
    source: str = Field(default="admin", min_length=2, max_length=120)


class RecommendationRequest(_StrictAdminModel):
    min_samples: int = Field(default=20, ge=5, le=10_000)


def _call(operation: Callable, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except GrowthValidationError as exc:
        status_code = 404 if "not_found" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def build_growth_router(require_admin: Callable) -> APIRouter:
    router = APIRouter(
        prefix="/admin/growth",
        tags=["admin-growth"],
        dependencies=[Depends(require_admin)],
    )

    @router.get("/dashboard")
    def dashboard():
        return growth_dashboard()

    @router.get("/prospects")
    def prospects(status: str | None = None, limit: int = 100):
        return list_prospects(status=status, limit=limit)

    @router.post("/prospects")
    def prospect_upsert(payload: ProspectRequest):
        return _call(upsert_prospect, **payload.model_dump())

    @router.post("/discovery/feed")
    def discovery_feed(payload: DiscoveryFeedRequest):
        return _call(discover_from_feed, payload.feed_url)

    @router.post("/prospects/{prospect_id}/qualify")
    def prospect_qualify(prospect_id: str):
        return _call(qualify_prospect, prospect_id)

    @router.get("/campaigns")
    def campaigns(limit: int = 100):
        return list_campaigns(limit=limit)

    @router.post("/campaigns")
    def campaign_create(payload: CampaignRequest):
        return _call(create_campaign, **payload.model_dump())

    @router.post("/campaigns/{campaign_id}/status")
    def campaign_status(campaign_id: str, payload: CampaignStatusRequest):
        return _call(set_campaign_status, campaign_id, payload.status)

    @router.get("/actions")
    def actions(status: str | None = None, limit: int = 100):
        return list_actions(status=status, limit=limit)

    @router.post("/actions/propose")
    def action_propose(payload: ActionProposalRequest):
        return _call(propose_action, payload.prospect_id, payload.campaign_id)

    @router.post("/actions/{action_id}/approve")
    def action_approve(action_id: str, payload: ActionApprovalRequest):
        return _call(
            approve_action,
            action_id,
            approved_by=payload.approved_by,
            reason=payload.reason,
        )

    @router.post("/actions/{action_id}/execute")
    def action_execute(action_id: str):
        return _call(execute_action, action_id)

    @router.post("/actions/{action_id}/retry")
    def action_retry(action_id: str, payload: ActionApprovalRequest):
        return _call(
            retry_action,
            action_id,
            approved_by=payload.approved_by,
            reason=payload.reason,
        )

    @router.post("/prospects/{prospect_id}/conversions")
    def conversion(prospect_id: str, payload: ConversionRequest):
        return _call(record_conversion, prospect_id, **payload.model_dump())

    @router.post("/cycle")
    def cycle():
        return run_growth_cycle()

    @router.get("/events")
    def events(event_type: str | None = None, limit: int = 200):
        return list_growth_events(event_type=event_type, limit=limit)

    @router.get("/responses")
    def responses(campaign_id: str | None = None, limit: int = 200):
        return list_responses(campaign_id=campaign_id, limit=limit)

    @router.get("/suppressions")
    def suppressions(limit: int = 100):
        return list_suppressions(limit=limit)

    @router.post("/suppressions")
    def suppression_create(payload: SuppressionRequest):
        return _call(suppress_prospect, **payload.model_dump())

    @router.get("/campaigns/{campaign_id}/analytics")
    def analytics(campaign_id: str):
        return _call(campaign_analytics, campaign_id)

    @router.post("/campaigns/{campaign_id}/recommendations")
    def recommendation_generate(campaign_id: str, payload: RecommendationRequest):
        return _call(
            generate_campaign_recommendation,
            campaign_id,
            min_samples=payload.min_samples,
        )

    @router.get("/recommendations")
    def recommendations(campaign_id: str | None = None, limit: int = 100):
        return list_recommendations(campaign_id=campaign_id, limit=limit)

    @router.post("/recommendations/{recommendation_id}/apply")
    def recommendation_apply(recommendation_id: str):
        return _call(apply_recommendation, recommendation_id)

    @router.post("/recommendations/{recommendation_id}/rollback")
    def recommendation_rollback(recommendation_id: str):
        return _call(rollback_recommendation, recommendation_id)

    return router
