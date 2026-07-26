"""Administrative GOIA catalog ingestion routes."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from iat.goia.contracts import MerchantProviderManifest, OfferObservation
from iat.goia.repository import (
    GOIARepositoryError,
    collection_job_stats,
    enqueue_collection_job,
    goia_index_stats,
    ingest_catalog,
)
from iat.goia.collector import GOIACollectionError, validate_collection_url


class CatalogIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: MerchantProviderManifest
    observations: list[OfferObservation] = Field(min_length=1, max_length=500)


class CollectionJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=8, max_length=2_000)


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

    return router
