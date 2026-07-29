"""Public, side-effect-free GOIA contract endpoints."""

from fastapi import APIRouter, Header, HTTPException

from iat.goia.contracts import (
    MerchantProviderManifest,
    NativeCatalogDocument,
    OfferObservation,
    PartnershipProposal,
    PartnershipAcknowledgement,
    PartnershipResponse,
    SearchIntent,
    evaluate_pilot_readiness,
)
from iat.goia.discovery import build_goia_manifest, build_ranking_policy
from iat.goia.search import search_local_index
from iat.goia.partnership_responses import (
    GOIAPartnershipResponseError,
    record_partner_response,
)


router = APIRouter(tags=["goia"])


@router.get("/.well-known/goia.json")
def goia_manifest():
    return build_goia_manifest()


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
