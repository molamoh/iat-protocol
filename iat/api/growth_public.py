"""Authenticated machine response channel for IAT growth invitations."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from iat.growth import GrowthValidationError, record_prospect_response


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
