"""Administrative GOIA catalog ingestion routes."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from iat.goia.contracts import MerchantProviderManifest, OfferObservation
from iat.goia.repository import (
    GOIARepositoryError,
    goia_index_stats,
    ingest_catalog,
)


class CatalogIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: MerchantProviderManifest
    observations: list[OfferObservation] = Field(min_length=1, max_length=500)


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

    return router
