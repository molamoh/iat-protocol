"""Public, side-effect-free GOIA contract endpoints."""

from typing import Any
import os
import secrets

from fastapi import APIRouter, Header, HTTPException

from iat.goia.contracts import (
    MerchantProviderManifest,
    NativeCatalogDocument,
    OfferObservation,
    PartnershipProposal,
    PartnershipAcknowledgement,
    PartnershipResponse,
    SearchIntent,
    OpenAICompatibleRuntime,
    MCPRuntime,
    evaluate_pilot_readiness,
)
from iat.goia.discovery import build_goia_manifest, build_ranking_policy
from iat.goia.search import search_local_index
from iat.goia.partnership_responses import (
    GOIAPartnershipResponseError,
    record_partner_response,
)
from iat.goia.prospecting import prospecting_policy, public_prospecting_sources
from iat.goia.repository import external_prospect_review_queue, external_prospect_status_counts


router = APIRouter(tags=["goia"])


@router.get("/goia/v1/reference-runtime/health")
def reference_runtime_health():
    return {"status": "ok", "runtime": "iat-reference-runtime", "provider_activation": False}


@router.get("/goia/v1/reference-runtime/v1/models")
def reference_runtime_models():
    return {
        "object": "list",
        "data": [{"id": "iat-reference-runtime", "object": "model", "owned_by": "iat"}],
    }


@router.post("/goia/v1/reference-runtime/v1/chat/completions")
def reference_runtime_chat(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    expected = os.getenv("IAT_REFERENCE_RUNTIME_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="reference_runtime_not_configured")
    supplied = (authorization or "").strip()
    if not supplied.lower().startswith("bearer ") or not secrets.compare_digest(
        supplied[7:].strip(), expected
    ):
        raise HTTPException(status_code=401, detail="reference_runtime_unauthorized")
    messages = payload.get("messages") or []
    last_message = messages[-1] if messages and isinstance(messages[-1], dict) else {}
    content = str(last_message.get("content") or "")[:2_000]
    return {
        "id": "iat_ref_" + __import__("uuid").uuid4().hex,
        "object": "chat.completion",
        "model": "iat-reference-runtime",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": (
                "IAT reference runtime received the authorized request. "
                "Execution evidence is sealed for protocol delivery. "
                f"Request summary: {content}"
            )},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "iat": {"execution_mode": "reference_runtime", "provider_activation": False},
    }


@router.get("/goia/v1/reference-runtime/v1/chat/completions")
def reference_runtime_chat_probe():
    """Allow seller registration probes without exposing execution."""
    return {
        "status": "ready",
        "runtime": "iat-reference-runtime",
        "method": "POST",
        "authentication": "bearer_required_for_execution",
        "provider_activation": False,
    }


@router.get("/goia/v1/reference-mcp/health")
def reference_mcp_health():
    return {"status": "ok", "server": "iat-reference-mcp", "provider_activation": False}


@router.get("/goia/v1/reference-mcp")
def reference_mcp_probe():
    return {"status": "ready", "server": "iat-reference-mcp", "method": "POST", "authentication": "bearer"}


@router.post("/goia/v1/reference-mcp")
def reference_mcp(payload: dict[str, Any], authorization: str | None = Header(default=None, alias="Authorization")):
    expected = os.getenv("IAT_REFERENCE_RUNTIME_API_KEY", "").strip()
    supplied = (authorization or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="reference_mcp_not_configured")
    if not supplied.lower().startswith("bearer ") or not secrets.compare_digest(supplied[7:].strip(), expected):
        raise HTTPException(status_code=401, detail="reference_mcp_unauthorized")
    method = str(payload.get("method") or "")
    request_id = payload.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "iat-reference-mcp", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "iat_validate_execution", "description": "Return sealed IAT execution evidence for a bounded request.", "inputSchema": {"type": "object", "properties": {"request": {"type": "string"}}, "required": ["request"]}}]}
    elif method == "tools/call":
        arguments = payload.get("params", {}).get("arguments", {})
        result = {"content": [{"type": "text", "text": "IAT reference MCP execution sealed: " + str(arguments.get("request") or "")[:2000]}], "isError": False}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method_not_found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


@router.get("/.well-known/goia.json")
def goia_manifest():
    return build_goia_manifest()


@router.get("/goia/v1/prospecting/sources")
def prospecting_sources():
    """Expose the passive discovery registry to agents and operators."""
    return {
        "status": "ok",
        "policy": prospecting_policy(),
        "sources": public_prospecting_sources(),
        "production_side_effects": False,
    }


@router.get("/goia/v1/prospecting/status")
def prospecting_status():
    """Expose aggregate pipeline state without prospect identities or URLs."""
    return external_prospect_status_counts()


@router.get("/goia/v1/prospecting/review-queue")
def public_prospecting_review_queue(limit: int = 100):
    """Expose redacted candidate metadata; decisions remain admin-only."""
    result = external_prospect_review_queue(limit=limit)
    return {
        "status": "ok",
        "governance_required": True,
        "provider_activation": False,
        "prospects": [
            {
                "prospect_id": item["prospect_id"],
                "source_id": item["source_id"],
                "name": item["name"],
                "governance_score": item["governance_score"],
                "governance_reasons": item["governance_reasons"],
                "recommendation": item["recommendation"],
            }
            for item in result["prospects"]
        ],
    }


@router.post("/goia/v1/contracts/search-intent/validate")
def validate_search_intent(payload: SearchIntent):
    return {
        "status": "valid",
        "contract": "SearchIntent",
        "normalized": payload.model_dump(mode="json"),
        "production_side_effects": False,
    }


@router.post("/goia/v1/contracts/offer-observation/validate")
def validate_offer_observation(payload: OfferObservation):
    return {
        "status": "valid",
        "contract": "OfferObservation",
        "normalized": payload.model_dump(mode="json"),
        "production_side_effects": False,
    }


@router.post("/goia/v1/contracts/provider/validate")
def validate_provider_manifest(payload: MerchantProviderManifest):
    return {
        "status": "valid",
        "contract": "MerchantProviderManifest",
        "normalized": payload.model_dump(mode="json"),
        "production_side_effects": False,
    }


@router.post("/goia/v1/contracts/runtime/openai-compatible/validate")
def validate_openai_compatible_runtime(payload: OpenAICompatibleRuntime):
    return {
        "status": "valid",
        "contract": "OpenAICompatibleRuntime",
        "normalized": payload.model_dump(mode="json"),
        "network_probe_performed": False,
        "provider_activation": False,
    }


@router.post("/goia/v1/contracts/runtime/mcp/validate")
def validate_mcp_runtime(payload: MCPRuntime):
    return {
        "status": "valid",
        "contract": "MCPRuntime",
        "normalized": payload.model_dump(mode="json"),
        "network_probe_performed": False,
        "provider_activation": False,
    }


@router.post("/goia/v1/pilots/readiness")
def validate_pilot_readiness(payload: MerchantProviderManifest):
    return evaluate_pilot_readiness(payload)


@router.post("/goia/v1/contracts/catalog/validate")
def validate_native_catalog(payload: NativeCatalogDocument):
    return {
        "status": "valid",
        "contract": "NativeCatalogDocument",
        "offer_count": len(payload.offers),
        "normalized": payload.model_dump(mode="json"),
        "production_side_effects": False,
    }


@router.post("/goia/v1/contracts/partnership-proposal/validate")
def validate_partnership_proposal(payload: PartnershipProposal):
    return {
        "status": "valid",
        "contract": "PartnershipProposal",
        "normalized": payload.model_dump(mode="json"),
        "production_side_effects": False,
    }


@router.post("/goia/v1/contracts/partnership-acknowledgement/validate")
def validate_partnership_acknowledgement(payload: PartnershipAcknowledgement):
    return {
        "status": "valid",
        "contract": "PartnershipAcknowledgement",
        "normalized": payload.model_dump(mode="json"),
        "production_side_effects": False,
    }


@router.post("/goia/v1/contracts/partnership-response/validate")
def validate_partnership_response(payload: PartnershipResponse):
    return {
        "status": "valid",
        "contract": "PartnershipResponse",
        "normalized": payload.model_dump(mode="json"),
        "production_side_effects": False,
    }


@router.post("/goia/v1/partnership/responses")
def partnership_response(
    payload: PartnershipResponse,
    signature: str = Header(
        alias="X-GOIA-Merchant-Signature",
        min_length=80,
        max_length=100,
    ),
    signed_at: int = Header(alias="X-GOIA-Signed-At", gt=0),
):
    try:
        return record_partner_response(
            payload,
            signature=signature,
            signed_at=signed_at,
        )
    except GOIAPartnershipResponseError as exc:
        detail = str(exc)
        status_code = 409 if "idempotency_conflict" in detail else 401
        if detail in {"proposal_not_found", "proposal_must_be_delivered"}:
            status_code = 422
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/goia/v1/policies/ranking")
def goia_ranking_policy():
    return build_ranking_policy()


@router.post("/goia/v1/search")
def goia_local_search(payload: SearchIntent):
    return search_local_index(payload)
