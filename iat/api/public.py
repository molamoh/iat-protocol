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
from iat.seller_growth import (
    SellerGrowthValidationError,
    build_integration_contract,
    build_seller_discovery,
    estimate_seller_economics,
    evaluate_seller_readiness,
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


class SellerEconomicsRequest(StrictPublicModel):
    unit_price: str = Field(pattern=r"^\d{1,9}(\.\d{1,6})?$")
    monthly_completed_orders: int = Field(ge=0, le=10_000_000)
    refund_rate: str = Field(default="0", pattern=r"^(0(\.\d{1,6})?|1(\.0{1,6})?)$")
    variable_cost_per_order: str = Field(default="0", pattern=r"^\d{1,9}(\.\d{1,6})?$")
    commission_rate: str | None = Field(
        default=None,
        pattern=r"^(0(\.\d{1,6})?|1(\.0{1,6})?)$",
    )


class SellerReadinessRequest(StrictPublicModel):
    seller_name: str | None = Field(default=None, max_length=120)
    wallet: str | None = Field(default=None, max_length=256)
    support_email: str | None = Field(default=None, max_length=320)
    service: str | None = Field(default=None, max_length=120)
    unit_price: str | None = Field(default=None, max_length=32)
    currency: str | None = Field(default="IAT", max_length=16)
    refund_policy: str | None = Field(default=None, max_length=2_000)
    runtime_adapter: Literal["http", "python", "internal"] | None = None
    runtime_url: str | None = Field(default=None, max_length=500)
    health_endpoint: str | None = Field(default=None, max_length=500)
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    input_schema: dict | None = None
    output_schema: dict | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=3_600)
    capacity_per_day: int | None = Field(default=None, ge=0, le=100_000_000)
    idempotency_supported: bool | None = None
    data_policy: str | None = Field(default=None, max_length=2_000)
    secret_handling: str | None = Field(default=None, max_length=2_000)
    incident_contact: str | None = Field(default=None, max_length=320)
    evidence_types: list[str] = Field(default_factory=list, max_length=50)


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
    "/seller/v1/discovery",
    tags=["seller"],
    summary="Discover the machine-oriented seller journey and commercial policy",
)
def seller_discovery():
    return build_seller_discovery()


@router.post(
    "/seller/v1/readiness",
    tags=["seller"],
    summary="Assess seller integration readiness without creating an account",
)
def seller_readiness(payload: SellerReadinessRequest):
    return evaluate_seller_readiness(payload.model_dump())


@router.post(
    "/seller/v1/economics/estimate",
    tags=["seller"],
    summary="Estimate transparent seller payouts and commission",
)
def seller_economics(payload: SellerEconomicsRequest):
    try:
        return estimate_seller_economics(**payload.model_dump())
    except SellerGrowthValidationError as exc:
        raise _client_error(exc) from exc


@router.get(
    "/seller/v1/integration-contract",
    tags=["seller"],
    summary="Inspect the runtime contract for a seller adapter",
)
def seller_integration_contract(
    runtime_adapter: Literal["http", "python", "internal"] = "http",
):
    try:
        return build_integration_contract(runtime_adapter)
    except SellerGrowthValidationError as exc:
        raise _client_error(exc) from exc


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
    from iat.api.growth_public import router as growth_public_router

    return get_openapi(
        title="IAT Protocol Public API",
        version=IAT_VERSION,
        description=(
            "Stable machine-discovery and isolated buyer sandbox contract. "
            "Sandbox routes never move funds or call production suppliers. "
            "Growth responses require invitation-scoped authentication."
        ),
        routes=[*router.routes, *growth_public_router.routes],
    )


@router.get(
    "/openapi-public.json",
    include_in_schema=False,
    summary="Download the stable public OpenAPI contract",
)
def public_openapi():
    return public_openapi_schema()
