"""Public, side-effect-free GOIA contract endpoints."""

from fastapi import APIRouter

from iat.goia.contracts import (
    MerchantProviderManifest,
    OfferObservation,
    SearchIntent,
)
from iat.goia.discovery import build_goia_manifest, build_ranking_policy


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


@router.get("/goia/v1/policies/ranking")
def goia_ranking_policy():
    return build_ranking_policy()
