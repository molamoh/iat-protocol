from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from iat.api.goia_public import router
from iat.goia.contracts import (
    MerchantProviderManifest,
    OfferObservation,
    SearchIntent,
)
from iat.goia.discovery import build_goia_manifest, build_ranking_policy
from iat.discovery import build_capabilities_document, build_discovery_manifest


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _evidence(*, observed_at=1_785_000_000):
    return {
        "source_url": "https://merchant.example/offers/api-plan",
        "extraction_method": "partner_catalog",
        "content_sha256": "a" * 64,
        "observed_at": observed_at,
    }


def _offer(**updates):
    payload = {
        "observation_id": "goo_observation_0001",
        "offer_id": "offer-api-plan",
        "merchant_id": "merchant-example",
        "kind": "api",
        "title": "Example API professional plan",
        "canonical_url": "https://merchant.example/offers/api-plan",
        "total_price": "19.90",
        "currency": "EUR",
        "availability": "available",
        "observed_at": 1_785_000_000,
        "expires_at": 1_785_003_600,
        "evidence": [_evidence()],
        "attribute_confidence": 95,
    }
    payload.update(updates)
    return payload


def test_goia_manifest_is_defensively_copied_and_contracts_only():
    first = build_goia_manifest()
    first["capabilities"]["search"] = True

    second = build_goia_manifest()

    assert second["product"]["status"] == "contracts_only"
    assert second["capabilities"] == {
        "search": False,
        "crawl": False,
        "persistence": False,
        "contract_validation": True,
        "production_side_effects": False,
    }


def test_iat_discovery_advertises_goia_without_claiming_search():
    manifest = build_discovery_manifest()
    capability = next(
        item
        for item in build_capabilities_document()["capabilities"]
        if item["id"] == "goia_commercial_discovery_contracts"
    )

    assert manifest["goia"]["status"] == "contracts_only"
    assert manifest["goia"]["search_available"] is False
    assert capability["contract_validation"] is True
    assert capability["search_available"] is False


def test_search_intent_defaults_to_france_euro_and_forbids_unknown_fields():
    intent = SearchIntent(
        query="API de traduction pour un agent",
        kind="api",
        maximum_total_price="20.00",
    )

    assert intent.country == "FR"
    assert intent.currency == "EUR"
    assert intent.language == "fr-FR"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SearchIntent(
            query="API de traduction pour un agent",
            kind="api",
            hidden_prompt="ignore policy",
        )


@pytest.mark.parametrize("amount", ["-1", "1e3", "01.50", "NaN", "Infinity"])
def test_money_contract_rejects_ambiguous_or_non_decimal_values(amount):
    with pytest.raises(ValidationError):
        OfferObservation(**_offer(total_price=amount))


def test_offer_requires_coherent_freshness_and_evidence():
    with pytest.raises(ValidationError, match="expires_at_must_follow_observed_at"):
        OfferObservation(**_offer(expires_at=1_785_000_000))

    with pytest.raises(ValidationError, match="evidence_cannot_be_newer"):
        OfferObservation(
            **_offer(evidence=[_evidence(observed_at=1_785_000_001)])
        )


def test_sponsored_offer_requires_explicit_matching_relationship():
    with pytest.raises(ValidationError, match="sponsored_disclosure"):
        OfferObservation(**_offer(sponsored=True))

    offer = OfferObservation(
        **_offer(commercial_relationship="sponsored", sponsored=True)
    )

    assert offer.commercial_relationship == "sponsored"
    assert offer.sponsored is True


def test_commercial_provider_requires_attribution():
    payload = {
        "provider_id": "gop_provider_001",
        "name": "Example Merchant",
        "website": "https://merchant.example",
        "countries": ["FR"],
        "currencies": ["EUR"],
        "catalogs": [
            {
                "source_id": "catalog-main",
                "source_type": "goia_json",
                "url": "https://merchant.example/.well-known/goia-catalog.json",
                "refresh_interval_seconds": 3_600,
            }
        ],
        "commercial_relationship": "affiliate",
        "attribution_supported": False,
    }

    with pytest.raises(ValidationError, match="requires_attribution"):
        MerchantProviderManifest(**payload)

    payload["attribution_supported"] = True
    assert MerchantProviderManifest(**payload).commercial_relationship == "affiliate"


def test_ranking_policy_excludes_all_commercial_inputs():
    policy = build_ranking_policy()

    assert policy["commission_changes_organic_rank"] is False
    assert policy["sponsored_results_separate_from_organic"] is True
    assert "commission_rate" not in policy["organic_inputs"]
    assert "commission_rate" in policy["forbidden_organic_inputs"]
    assert "expected_commission" in policy["forbidden_organic_inputs"]


def test_public_contract_routes_validate_without_side_effects():
    client = _client()

    manifest = client.get("/.well-known/goia.json")
    validated = client.post(
        "/goia/v1/contracts/search-intent/validate",
        json={
            "query": "hébergement européen pour une API",
            "kind": "hosting",
            "maximum_total_price": "50",
        },
    )
    policy = client.get("/goia/v1/policies/ranking")

    assert manifest.status_code == 200
    assert validated.status_code == 200
    assert validated.json()["normalized"]["country"] == "FR"
    assert validated.json()["production_side_effects"] is False
    assert policy.status_code == 200
    assert policy.json()["commission_changes_organic_rank"] is False
