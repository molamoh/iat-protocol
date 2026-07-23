"""Stable public discovery and zero-funds sandbox API."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.openapi.utils import get_openapi
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from iat.config import IAT_VERSION
from iat.discovery import (
    build_capabilities_document,
    build_discovery_manifest,
    build_llms_document,
)
from iat.sandbox import (
    BuyerSandbox,
    SandboxConflictError,
    SandboxNotFoundError,
    SandboxValidationError,
)


router = APIRouter()
buyer_sandbox = BuyerSandbox()


class StrictPublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SandboxPreviewRequest(StrictPublicModel):
    service: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=4_000)
    max_price: str = Field(pattern=r"^\d{1,7}(\.\d{1,6})?$")
    strategy: Literal["balanced", "cheapest", "fastest", "safest", "quality"] = "balanced"
    required_capabilities: list[str] = Field(default_factory=list, max_length=20)


class SandboxFeedbackRequest(StrictPublicModel):
    outcome: Literal["positive", "negative"]
    feedback_key: str = Field(min_length=8, max_length=128)


def _client_error(exc: Exception, *, status_code: int = 422) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get(
    "/.well-known/iat.json",
    tags=["discovery"],
    summary="Discover the IAT machine interface",
)
def discovery_manifest():
    return build_discovery_manifest()


@router.get(
    "/v1/capabilities",
    tags=["discovery"],
    summary="Inspect autonomous capabilities and safety invariants",
)
def capabilities():
    return build_capabilities_document()


@router.get(
    "/llms.txt",
    response_class=PlainTextResponse,
    tags=["discovery"],
    summary="Read the AI-oriented protocol navigation document",
)
def llms_document():
    return build_llms_document()


@router.get(
    "/sandbox/v1/offers",
    tags=["sandbox"],
    summary="List deterministic no-funds sandbox offers",
)
def sandbox_offers(
    service: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
):
    return {
        "status": "ok",
        "sandbox": True,
        "production_side_effects": False,
        "offers": buyer_sandbox.list_offers(service=service),
    }


@router.post(
    "/sandbox/v1/preview",
    tags=["sandbox"],
    summary="Compare eligible offers without creating an order",
)
def sandbox_preview(payload: SandboxPreviewRequest):
    try:
        return buyer_sandbox.preview(**payload.model_dump())
    except SandboxValidationError as exc:
        raise _client_error(exc) from exc


@router.post(
    "/sandbox/v1/purchase",
    tags=["sandbox"],
    summary="Execute an isolated, idempotent, no-funds purchase simulation",
)
def sandbox_purchase(
    payload: SandboxPreviewRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
):
    try:
        return buyer_sandbox.purchase(
            **payload.model_dump(),
            idempotency_key=idempotency_key,
        )
    except SandboxConflictError as exc:
        raise _client_error(exc, status_code=409) from exc
    except SandboxValidationError as exc:
        raise _client_error(exc) from exc


@router.get(
    "/sandbox/v1/orders/{order_id}",
    tags=["sandbox"],
    summary="Inspect a sandbox order and its simulation receipt",
)
def sandbox_order(order_id: str):
    try:
        return buyer_sandbox.get_order(order_id)
    except SandboxNotFoundError as exc:
        raise _client_error(exc, status_code=404) from exc
    except SandboxValidationError as exc:
        raise _client_error(exc) from exc


@router.post(
    "/sandbox/v1/orders/{order_id}/feedback",
    tags=["sandbox"],
    summary="Submit idempotent feedback for bounded sandbox-only learning",
)
def sandbox_feedback(order_id: str, payload: SandboxFeedbackRequest):
    try:
        return buyer_sandbox.record_feedback(
            order_id,
            outcome=payload.outcome,
            feedback_key=payload.feedback_key,
        )
    except SandboxNotFoundError as exc:
        raise _client_error(exc, status_code=404) from exc
    except SandboxValidationError as exc:
        raise _client_error(exc) from exc


@lru_cache(maxsize=1)
def public_openapi_schema() -> dict:
    return get_openapi(
        title="IAT Protocol Public API",
        version=IAT_VERSION,
        description=(
            "Stable machine-discovery and isolated buyer sandbox contract. "
            "Sandbox routes never move funds or call production suppliers."
        ),
        routes=router.routes,
    )


@router.get(
    "/openapi-public.json",
    include_in_schema=False,
    summary="Download the stable public OpenAPI contract",
)
def public_openapi():
    return public_openapi_schema()
