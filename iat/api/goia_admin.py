"""Administrative GOIA catalog ingestion routes."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from iat.goia.contracts import MerchantProviderManifest, OfferObservation
from iat.goia.repository import (
    GOIARepositoryError,
    collection_job_stats,
    demand_signal_stats,
    approve_review_candidate,
    enqueue_collection_job,
    goia_index_stats,
    ingest_catalog,
    list_review_candidates,
    list_partnership_opportunities,
    list_partner_prospects,
    list_provider_verifications,
    list_partner_proposals,
    list_partner_delivery_events,
    list_partner_suppressions,
    list_worker_health,
    prepare_partner_proposals,
    refresh_partnership_opportunities,
    refresh_partner_permissions,
    reject_review_candidate,
)
from iat.goia.collector import GOIACollectionError, validate_collection_url
from iat.goia.partnership_responses import list_partner_relationships


class CatalogIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: MerchantProviderManifest
    observations: list[OfferObservation] = Field(min_length=1, max_length=500)


class CollectionJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider_id: str = Field(pattern=r"^gop_[a-zA-Z0-9_-]{8,100}$")
    url: str = Field(min_length=8, max_length=2_000)


class CandidateApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reviewer: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=8, max_length=1_000)
    observation: OfferObservation


class CandidateRejectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reviewer: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=8, max_length=1_000)


def build_goia_admin_router(require_admin: Callable) -> APIRouter:
    router = APIRouter(
        prefix="/admin/goia",
        tags=["admin-goia"],
        dependencies=[Depends(require_admin)],
    )

    @router.post("/catalogs/ingest")
    def catalog_ingest(payload: CatalogIngestRequest):
        try:
            return ingest_catalog(payload.provider, payload.observations)
        except GOIARepositoryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/index/stats")
    def index_stats():
        return goia_index_stats()

    @router.post("/collection/jobs")
    def create_collection_job(
        payload: CollectionJobRequest,
        idempotency_key: str = Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
        ),
    ):
        try:
            validate_collection_url(payload.url)
            return enqueue_collection_job(
                provider_id=payload.provider_id,
                url=payload.url,
                idempotency_key=idempotency_key,
            )
        except GOIACollectionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GOIARepositoryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/collection/stats")
    def collection_stats():
        return collection_job_stats()

    @router.get("/workers/health")
    def workers_health(stale_after_seconds: int = 180):
        return list_worker_health(stale_after_seconds=stale_after_seconds)

    @router.get("/demand/stats")
    def demand_stats(days: int = 30):
        return demand_signal_stats(days=days)

    @router.post("/partnership/opportunities/refresh")
    def refresh_opportunities(days: int = 30):
        return refresh_partnership_opportunities(days=days)

    @router.get("/partnership/opportunities")
    def partnership_opportunities(
        status: str | None = None,
        limit: int = 100,
    ):
        try:
            return list_partnership_opportunities(status=status, limit=limit)
        except GOIARepositoryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/partnership/prospects")
    def partnership_prospects(status: str | None = None, limit: int = 100):
        try:
            return list_partner_prospects(status=status, limit=limit)
        except GOIARepositoryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/partnership/permissions/refresh")
    def refresh_permissions():
        return refresh_partner_permissions()

    @router.get("/partnership/verifications")
    def partnership_verifications(limit: int = 100):
        return list_provider_verifications(limit=limit)

    @router.post("/partnership/proposals/prepare")
    def prepare_proposals(limit: int = 100):
        return prepare_partner_proposals(limit=limit)

    @router.get("/partnership/proposals")
    def partnership_proposals(status: str | None = None, limit: int = 100):
        try:
            return list_partner_proposals(status=status, limit=limit)
        except GOIARepositoryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/partnership/delivery/events")
    def partnership_delivery_events(
        proposal_id: str | None = None,
        limit: int = 100,
    ):
        return list_partner_delivery_events(proposal_id=proposal_id, limit=limit)

    @router.get("/partnership/suppressions")
    def partnership_suppressions(limit: int = 100):
        return list_partner_suppressions(limit=limit)

    @router.get("/partnership/relationships")
    def partnership_relationships(limit: int = 100):
        return list_partner_relationships(limit=limit)

    @router.get("/review/candidates")
    def review_candidates(status: str = "pending_review", limit: int = 100):
        try:
            return list_review_candidates(status=status, limit=limit)
        except GOIARepositoryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/review/candidates/{candidate_id}/approve")
    def approve_candidate(candidate_id: str, payload: CandidateApprovalRequest):
        try:
            return approve_review_candidate(
                candidate_id,
                observation=payload.observation,
                reviewer=payload.reviewer,
                reason=payload.reason,
            )
        except GOIARepositoryError as exc:
            status_code = 404 if str(exc) == "candidate_not_found" else 409
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @router.post("/review/candidates/{candidate_id}/reject")
    def reject_candidate(candidate_id: str, payload: CandidateRejectionRequest):
        try:
            return reject_review_candidate(
                candidate_id,
                reviewer=payload.reviewer,
                reason=payload.reason,
            )
        except GOIARepositoryError as exc:
            status_code = 404 if str(exc) == "candidate_not_found" else 409
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return router
