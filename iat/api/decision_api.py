"""Governed administrative API for decision outcomes and calibration."""

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from iat.intelligence.decision_learning import (
    DecisionOutcomeError,
    decision_calibration,
    list_decision_outcomes,
    record_decision_outcome,
)


class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision_hash: str = Field(min_length=64, max_length=64)
    outcome_key: str = Field(min_length=8, max_length=160)
    decision_type: str = Field(min_length=3, max_length=80)
    outcome_type: str = Field(min_length=3, max_length=40)
    predicted_utility: float = Field(ge=0, le=1)
    observed_utility: float = Field(ge=0, le=1)
    metadata: dict = Field(default_factory=dict)


def build_decision_router(require_admin: Callable) -> APIRouter:
    router = APIRouter(
        prefix="/admin/intelligence",
        tags=["admin-intelligence"],
        dependencies=[Depends(require_admin)],
    )

    @router.post("/outcomes")
    def outcome_record(payload: OutcomeRequest):
        try:
            return record_decision_outcome(**payload.model_dump())
        except DecisionOutcomeError as exc:
            raise HTTPException(status_code=409 if "conflict" in str(exc) else 422, detail=str(exc)) from exc

    @router.get("/outcomes")
    def outcomes(decision_type: str | None = None, limit: int = 200):
        return list_decision_outcomes(decision_type=decision_type, limit=limit)

    @router.get("/calibration")
    def calibration(decision_type: str | None = None, limit: int = 500):
        return decision_calibration(decision_type=decision_type, limit=limit)

    return router
