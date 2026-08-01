"""Authenticated machine response channel for IAT growth invitations."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from iat.growth import (
    GrowthValidationError,
    record_prospect_response,
    register_inbound_pilot,
)


router = APIRouter(prefix="/growth/v1", tags=["growth-response"])


class GrowthResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action_id: str = Field(min_length=10, max_length=100)
    response_token: str = Field(min_length=32, max_length=256)
    idempotency_key: str = Field(min_length=8, max_length=160)
    response_type: Literal[
        "interested", "not_interested", "needs_info", "integrated", "opt_out"
    ]
    message: str = Field(default="", max_length=4_000)
    metadata: dict = Field(default_factory=dict)


class PilotApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=8, max_length=2_000)
    name: str = Field(min_length=2, max_length=200)
    segment: Literal[
        "ai_agent", "agent_platform", "marketplace", "framework", "seller"
    ]
    use_case: str = Field(min_length=10, max_length=1_000)
    source: str = Field(default="direct", min_length=2, max_length=80)
    referral: str = Field(default="", max_length=120)
    outreach_opt_in: bool


@router.get("/pilot")
def pilot_information():
    return {
        "status": "open",
        "program": "IAT USDC-to-IAT autonomous commerce pilot",
        "network": "solana-devnet",
        "cost": "devnet_assets_only",
        "eligible_segments": [
            "ai_agent", "agent_platform", "marketplace", "framework", "seller"
        ],
        "apply": {"method": "POST", "href": "/growth/v1/pilot"},
        "requirements": [
            "public_http_or_https_agent_url",
            "explicit_follow_up_opt_in",
            "machine_commerce_use_case",
        ],
    }


@router.post("/pilot", status_code=202)
def apply_to_pilot(payload: PilotApplicationRequest):
    try:
        return register_inbound_pilot(**payload.model_dump())
    except GrowthValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/respond")
def respond(payload: GrowthResponseRequest):
    try:
        return record_prospect_response(**payload.model_dump())
    except GrowthValidationError as exc:
        detail = str(exc)
        if detail == "invalid_response_token":
            status_code = 401
        elif detail == "action_not_found":
            status_code = 404
        elif detail in {
            "response_requires_executed_action",
            "response_idempotency_conflict",
        }:
            status_code = 409
        else:
            status_code = 422
        raise HTTPException(status_code=status_code, detail=detail) from exc
