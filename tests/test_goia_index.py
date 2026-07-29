import sqlite3

import pytest

from iat.goia.contracts import (
    MerchantProviderManifest,
    OfferObservation,
    SearchIntent,
)
import iat.goia.repository as repository
import iat.goia.partnership_dispatcher as partnership_dispatcher
from iat.goia.search import search_local_index


@pytest.fixture()
def goia_db(tmp_path, monkeypatch):
    database = tmp_path / "goia.db"

    def connect():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(repository, "get_conn", connect)
    monkeypatch.setattr(repository, "release_conn", lambda conn: conn.close())
    monkeypatch.setattr(repository, "qmark", lambda: "?")
    repository.init_goia_tables()
    return database


def _provider(**updates):
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
        "commercial_relationship": "none",
        "attribution_supported": False,
    }
    payload.update(updates)
    return MerchantProviderManifest(**payload)


def _observation(identifier, **updates):
    payload = {
        "observation_id": f"goo_{identifier}",
        "offer_id": f"offer-{identifier}",
        "merchant_id": "gop_provider_001",
        "kind": "api",
        "title": "API traduction professionnelle",
        "canonical_url": f"https://merchant.example/offers/{identifier}",
        "total_price": "20.00",
        "currency": "EUR",
        "availability": "available",
        "observed_at": 1_000,
        "expires_at": 2_000,
        "evidence": [
            {
                "source_url": f"https://merchant.example/offers/{identifier}",
                "extraction_method": "partner_catalog",
                "content_sha256": "a" * 64,
                "observed_at": 1_000,
            }
        ],
        "attribute_confidence": 90,
    }
    payload.update(updates)
    return OfferObservation(**payload)


def test_catalog_ingestion_is_idempotent(goia_db):
    provider = _provider()
    observation = _observation("observation001")

    first = repository.ingest_catalog(provider, [observation], now=1_100)
    second = repository.ingest_catalog(provider, [observation], now=1_200)

    assert first["provider"]["state"] == "created"
    assert first["observations"]["created"] == 1
    assert second["provider"]["state"] == "unchanged"
    assert second["observations"]["duplicates"] == 1
    assert repository.goia_index_stats(now=1_500)["observations"] == 1


def test_observation_identity_rejects_different_payload(goia_db):
    provider = _provider()
    repository.ingest_catalog(provider, [_observation("observation001")], now=1_100)

    with pytest.raises(repository.GOIARepositoryError, match="payload_conflict"):
        repository.ingest_catalog(
            provider,
            [_observation("observation001", total_price="21.00")],
            now=1_200,
        )


def test_catalog_rejects_offer_from_another_merchant(goia_db):
    with pytest.raises(repository.GOIARepositoryError, match="merchant_mismatch"):
        repository.ingest_catalog(
            _provider(),
            [_observation("observation001", merchant_id="gop_other_001")],
        )


def test_local_search_filters_country_budget_expiry_and_sponsored(goia_db):
    provider = _provider()
    repository.ingest_catalog(
        provider,
        [
            _observation("validoffer001", total_price="20.00"),
            _observation("expensive001", total_price="80.00"),
            _observation("expired00000", expires_at=1_400),
            _observation(
                "sponsored001",
                commercial_relationship="sponsored",
                sponsored=True,
            ),
        ],
        now=1_100,
    )

    result = search_local_index(
        SearchIntent(
            query="API traduction",
            kind="api",
            maximum_total_price="50",
        ),
        now=1_500,
    )

    assert result["status"] == "ok"
    assert result["network_access"] is False
    assert result["result_count"] == 1
    assert result["results"][0]["observation"]["observation_id"] == "goo_validoffer001"
    assert result["results"][0]["commercial_disclosure"] == {
        "commercial_relationship": "none",
        "sponsored": False,
        "commission_may_be_earned": False,
        "commission_changes_organic_rank": False,
    }


def test_commission_relationship_does_not_change_organic_score(goia_db):
    provider = _provider(
        commercial_relationship="affiliate",
        attribution_supported=True,
    )
    repository.ingest_catalog(
        provider,
        [
            _observation("affiliate001", commercial_relationship="affiliate"),
            _observation("organic00001", commercial_relationship="none"),
        ],
        now=1_100,
    )

    results = search_local_index(
        SearchIntent(query="API traduction", kind="api"),
        now=1_500,
    )["results"]

    assert len(results) == 2
    assert results[0]["organic_score"] == results[1]["organic_score"]
    assert all(
        item["commercial_disclosure"]["commission_changes_organic_rank"] is False
        for item in results
    )


def test_unsupported_requirements_fail_explicitly_without_search(goia_db):
    result = search_local_index(
        SearchIntent(
            query="API traduction",
            kind="api",
            required=[
                {
                    "attribute": "monthly_requests",
                    "operator": "gte",
                    "value": 10_000,
                }
            ],
        ),
        now=1_500,
    )

    assert result["status"] == "unsupported_constraints"
    assert result["search_performed"] is False
    assert result["unsupported_attributes"] == ["monthly_requests"]


def test_search_aggregates_demand_without_raw_query_or_buyer_identity(goia_db):
    intent = SearchIntent(
        query="service extrêmement spécifique et confidentiel",
        kind="digital_service",
    )

    first = search_local_index(intent, now=86_400)
    second = search_local_index(intent, now=86_401)
    stats = repository.demand_signal_stats(days=30, now=86_401)

    assert first["anonymous_demand_aggregated"] is True
    assert second["anonymous_demand_aggregated"] is True
    assert stats["markets"][0]["demand_count"] == 2
    assert stats["markets"][0]["unmet_count"] == 2
    assert stats["privacy"] == {
        "buyer_identity_stored": False,
        "raw_query_stored": False,
        "query_fingerprint_only": True,
    }

    connection = sqlite3.connect(goia_db)
    stored = connection.execute(
        "SELECT query_fingerprint FROM goia_demand_signals"
    ).fetchone()[0]
    connection.close()
    assert len(stored) == 64
    assert "confidentiel" not in stored


def test_unmet_demand_creates_ranked_partnership_opportunity(goia_db):
    fingerprint = "f" * 64
    for offset in range(5):
        repository.record_anonymous_demand(
            query_fingerprint=fingerprint,
            kind="hosting",
            country="FR",
            currency="EUR",
            result_count=0,
            now=86_400 + offset,
        )

    refreshed = repository.refresh_partnership_opportunities(
        days=30,
        now=86_500,
    )
    opportunities = repository.list_partnership_opportunities(status="qualified")

    assert refreshed["qualified_count"] == 1
    assert refreshed["outreach_triggered"] is False
    assert opportunities["count"] == 1
    opportunity = opportunities["items"][0]
    assert opportunity["kind"] == "hosting"
    assert opportunity["gap_score"] >= 60
    assert opportunity["evidence"]["raw_queries_included"] is False
    assert opportunity["evidence"]["buyer_identity_included"] is False
    assert opportunities["outreach_triggered"] is False


def test_satisfied_low_volume_demand_remains_monitoring(goia_db):
    repository.record_anonymous_demand(
        query_fingerprint="e" * 64,
        kind="api",
        country="FR",
        currency="EUR",
        result_count=3,
        now=86_400,
    )

    repository.refresh_partnership_opportunities(days=30, now=86_500)
    monitoring = repository.list_partnership_opportunities(status="monitoring")

    assert monitoring["count"] == 1
    assert monitoring["items"][0]["unmet_count"] == 0
    assert monitoring["items"][0]["reason"] == "insufficient_gap_evidence"


def test_partner_prospect_requires_repeated_structured_evidence(goia_db):
    base = {
        "domain": "merchant.example",
        "name": "Merchant",
        "url": "https://merchant.example/offer",
        "source_url": "https://comparison.example/cloud",
        "source_sha256": "a" * 64,
        "evidence_type": "schema_offer_seller",
        "kinds": ["Service"],
        "currencies": ["EUR"],
    }
    first = repository.upsert_partner_hints([base], now=1_000)
    repository.upsert_partner_hints(
        [{**base, "source_url": "https://comparison.example/cloud-2", "source_sha256": "b" * 64}],
        now=1_001,
    )
    prospects = repository.list_partner_prospects()

    assert first["network_access_performed"] is False
    assert first["outreach_triggered"] is False
    assert prospects["count"] == 1
    assert prospects["items"][0]["status"] == "qualified"
    assert prospects["items"][0]["evidence_count"] == 2
    assert prospects["items"][0]["outreach_authorized"] is False
    assert prospects["items"][0]["contact_attempted"] is False


def test_qualified_prospect_links_to_market_gap_without_outreach(goia_db):
    for offset in range(5):
        repository.record_anonymous_demand(
            query_fingerprint="d" * 64,
            kind="hosting",
            country="FR",
            currency="EUR",
            result_count=0,
            now=86_400 + offset,
        )
    repository.refresh_partnership_opportunities(days=30, now=86_500)
    hint = {
        "domain": "host.example",
        "name": "Host",
        "url": "https://host.example/plans",
        "source_url": "https://comparison.example/a",
        "source_sha256": "a" * 64,
        "evidence_type": "schema_offer_seller",
        "kinds": ["Service"],
        "currencies": ["EUR"],
    }
    repository.upsert_partner_hints([hint], now=86_501)
    repository.upsert_partner_hints(
        [{**hint, "source_url": "https://comparison.example/b", "source_sha256": "b" * 64}],
        now=86_502,
    )

    linked = repository.refresh_opportunity_prospect_links(now=86_503)

    assert linked["linked_count"] == 1
    assert linked["outreach_triggered"] is False


def test_partner_permission_requires_domain_matched_explicit_opt_in(goia_db):
    provider = _provider(
        partnership_discovery={
            "accepts_partnership_requests": True,
            "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
            "request_endpoint": "https://merchant.example/.well-known/goia-partnership",
            "terms_url": "https://merchant.example/partner-terms",
            "relationship_types": ["affiliate"],
        }
    )
    repository.upsert_merchant(provider, now=1_000)
    hint = {
        "domain": "merchant.example",
        "name": "Merchant",
        "url": "https://merchant.example/offer",
        "source_url": "https://comparison.example/cloud",
        "source_sha256": "a" * 64,
        "evidence_type": "schema_offer_seller",
        "kinds": ["Service"],
        "currencies": ["EUR"],
    }
    repository.upsert_partner_hints([hint], now=1_001)

    refreshed = repository.refresh_partner_permissions(now=1_002)
    prospect = repository.list_partner_prospects()["items"][0]

    assert refreshed["declared_opt_in_count"] == 1
    assert refreshed["verified_opt_in_count"] == 0
    assert refreshed["outreach_triggered"] is False
    assert prospect["permission_status"] == "declared_opt_in"
    assert prospect["permission_provider_id"] == provider.provider_id
    assert prospect["permission_evidence"]["domain_match"] is True
    assert prospect["permission_evidence"]["self_hosting_verified"] is False
    assert prospect["outreach_authorized"] is False


def test_manifest_verification_rejects_non_matching_registered_payload(goia_db):
    registered = _provider(
        partnership_discovery={
            "accepts_partnership_requests": True,
            "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
            "request_endpoint": "https://merchant.example/goia-partnership",
            "relationship_types": ["affiliate"],
        }
    )
    repository.upsert_merchant(registered, now=1_000)
    changed = _provider(
        partnership_discovery={
            "accepts_partnership_requests": True,
            "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
            "request_endpoint": "https://merchant.example/other-endpoint",
            "relationship_types": ["affiliate"],
        }
    )

    with pytest.raises(repository.GOIARepositoryError, match="hash_mismatch"):
        repository.record_provider_manifest_verification(
            provider_id=registered.provider_id,
            manifest=changed,
            source_url=str(changed.partnership_discovery.manifest_url),
            source_sha256="c" * 64,
            now=1_001,
        )


def test_affiliate_relationship_alone_is_not_partnership_permission(goia_db):
    provider = _provider(
        commercial_relationship="affiliate",
        attribution_supported=True,
    )
    repository.upsert_merchant(provider, now=1_000)
    repository.upsert_partner_hints(
        [
            {
                "domain": "merchant.example",
                "name": "Merchant",
                "url": "https://merchant.example/offer",
                "source_url": "https://comparison.example/cloud",
                "source_sha256": "a" * 64,
                "evidence_type": "schema_offer_seller",
                "kinds": ["Service"],
                "currencies": ["EUR"],
            }
        ],
        now=1_001,
    )

    refreshed = repository.refresh_partner_permissions(now=1_002)
    prospect = repository.list_partner_prospects()["items"][0]

    assert refreshed["declared_opt_in_count"] == 0
    assert prospect["permission_status"] == "none"
    assert prospect["outreach_authorized"] is False


def test_withdrawn_partner_opt_in_is_revoked_autonomously(goia_db):
    provider = _provider(
        partnership_discovery={
            "accepts_partnership_requests": True,
            "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
            "request_endpoint": "https://merchant.example/goia-partnership",
            "relationship_types": ["direct_partner"],
        }
    )
    repository.upsert_merchant(provider, now=1_000)
    repository.upsert_partner_hints(
        [
            {
                "domain": "merchant.example",
                "name": "Merchant",
                "url": "https://merchant.example/offer",
                "source_url": "https://comparison.example/cloud",
                "source_sha256": "a" * 64,
                "evidence_type": "schema_offer_seller",
                "kinds": ["Service"],
                "currencies": ["EUR"],
            }
        ],
        now=1_001,
    )
    repository.refresh_partner_permissions(now=1_002)
    repository.upsert_merchant(_provider(), now=1_003)

    revoked = repository.refresh_partner_permissions(now=1_004)
    prospect = repository.list_partner_prospects()["items"][0]

    assert revoked["declared_opt_in_count"] == 0
    assert prospect["permission_status"] == "none"
    assert prospect["permission_provider_id"] is None
    assert prospect["permission_evidence"] is None
    assert prospect["outreach_authorized"] is False


def test_self_hosted_manifest_verification_authorizes_endpoint_without_sending(goia_db):
    provider = _provider(
        partnership_discovery={
            "accepts_partnership_requests": True,
            "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
            "request_endpoint": "https://merchant.example/goia-partnership",
            "relationship_types": ["affiliate"],
            "verification_interval_seconds": 3_600,
        }
    )
    repository.upsert_merchant(provider, now=1_000)
    repository.upsert_partner_hints(
        [
            {
                "domain": "merchant.example",
                "name": "Merchant",
                "url": "https://merchant.example/offer",
                "source_url": "https://comparison.example/cloud",
                "source_sha256": "a" * 64,
                "evidence_type": "schema_offer_seller",
                "kinds": ["Service"],
                "currencies": ["EUR"],
            }
        ],
        now=1_001,
    )
    verification = repository.record_provider_manifest_verification(
        provider_id=provider.provider_id,
        manifest=provider,
        source_url=str(provider.partnership_discovery.manifest_url),
        source_sha256="b" * 64,
        now=1_002,
    )

    refreshed = repository.refresh_partner_permissions(now=1_003)
    prospect = repository.list_partner_prospects()["items"][0]

    assert verification["status"] == "verified"
    assert refreshed["verified_opt_in_count"] == 1
    assert refreshed["outreach_triggered"] is False
    assert prospect["permission_status"] == "verified_opt_in"
    assert prospect["permission_evidence"]["self_hosting_verified"] is True
    assert prospect["outreach_authorized"] is True
    assert prospect["contact_attempted"] is False

    expired = repository.refresh_partner_permissions(now=8_203)
    prospect = repository.list_partner_prospects()["items"][0]
    assert expired["verified_opt_in_count"] == 0
    assert prospect["permission_status"] == "declared_opt_in"
    assert prospect["outreach_authorized"] is False


def test_verified_market_match_prepares_private_idempotent_proposal(goia_db):
    provider = _provider(
        partnership_discovery={
            "accepts_partnership_requests": True,
            "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
            "request_endpoint": "https://merchant.example/goia-partnership",
            "relationship_types": ["affiliate"],
            "verification_interval_seconds": 86_400,
        }
    )
    repository.upsert_merchant(provider, now=86_000)
    hint = {
        "domain": "merchant.example",
        "name": "Merchant",
        "url": "https://merchant.example/offer",
        "source_url": "https://comparison.example/cloud-a",
        "source_sha256": "a" * 64,
        "evidence_type": "schema_offer_seller",
        "kinds": ["Service"],
        "currencies": ["EUR"],
    }
    repository.upsert_partner_hints([hint], now=86_001)
    repository.upsert_partner_hints(
        [{**hint, "source_url": "https://comparison.example/cloud-b", "source_sha256": "b" * 64}],
        now=86_002,
    )
    for offset in range(5):
        repository.record_anonymous_demand(
            query_fingerprint="e" * 64,
            kind="hosting",
            country="FR",
            currency="EUR",
            result_count=0,
            now=86_000 + offset,
        )
    repository.refresh_partnership_opportunities(days=30, now=86_010)
    repository.record_provider_manifest_verification(
        provider_id=provider.provider_id,
        manifest=provider,
        source_url=str(provider.partnership_discovery.manifest_url),
        source_sha256="c" * 64,
        now=86_011,
    )
    repository.refresh_partner_permissions(now=86_012)
    repository.refresh_opportunity_prospect_links(now=86_013)

    first = repository.prepare_partner_proposals(now=86_014)
    duplicate = repository.prepare_partner_proposals(now=86_015)
    outbox = repository.list_partner_proposals(status="prepared")

    assert first["prepared_count"] == 1
    assert first["delivery_enabled"] is False
    assert first["network_access_performed"] is False
    assert first["outreach_triggered"] is False
    assert duplicate["prepared_count"] == 0
    assert duplicate["duplicate_count"] == 1
    assert outbox["count"] == 1
    payload = outbox["items"][0]["payload"]
    assert payload["raw_queries_included"] is False
    assert payload["buyer_identity_included"] is False
    assert payload["aggregate_evidence"]["unmet_count"] == 5
    assert payload["request_endpoint"] == "https://merchant.example/goia-partnership"

    connection = sqlite3.connect(goia_db)
    connection.execute(
        "UPDATE goia_partner_prospects SET outreach_authorized = 0"
    )
    connection.commit()
    connection.close()
    assert repository.claim_partner_proposal(now=86_016) is None
    connection = sqlite3.connect(goia_db)
    connection.execute(
        """
        UPDATE goia_partner_prospects
        SET outreach_authorized = 1, permission_status = 'verified_opt_in'
        """
    )
    connection.commit()
    connection.close()

    first_claim = repository.claim_partner_proposal(now=86_016)
    retry = repository.finish_partner_proposal_delivery(
        first_claim["proposal_id"],
        lease_token=first_claim["lease_token"],
        delivered=False,
        retryable=True,
        error_code="temporary_unavailable",
        now=86_016,
    )
    assert retry["status"] == "retryable"
    assert repository.claim_partner_proposal(now=86_135) is None
    second_claim = repository.claim_partner_proposal(now=86_136)
    recovered = repository.recover_stale_partner_deliveries(
        now=second_claim["lease_until"],
    )
    third_claim = repository.claim_partner_proposal(now=second_claim["lease_until"])
    delivered = repository.finish_partner_proposal_delivery(
        third_claim["proposal_id"],
        lease_token=third_claim["lease_token"],
        delivered=True,
        now=second_claim["lease_until"],
    )
    events = repository.list_partner_delivery_events(
        proposal_id=first_claim["proposal_id"]
    )
    prospect = repository.list_partner_prospects()["items"][0]

    assert recovered["recovered_count"] == 1
    assert delivered["status"] == "delivered"
    assert prospect["contact_attempted"] is True
    assert [item["event_type"] for item in events["items"]] == [
        "delivery_claimed",
        "delivery_failed",
        "delivery_claimed",
        "stale_lease_recovered",
        "delivery_claimed",
        "delivery_completed",
    ]


def test_partnership_dispatcher_is_fail_closed_by_default(monkeypatch):
    monkeypatch.delenv("IAT_GOIA_PARTNERSHIP_DELIVERY_ENABLED", raising=False)
    called = []

    result = partnership_dispatcher.process_one_delivery(
        sender=lambda proposal: called.append(proposal),
    )

    assert result == {
        "status": "disabled",
        "reason": "explicit_enable_required",
        "network_access_performed": False,
    }
    assert called == []


def test_enabled_dispatcher_still_requires_delivery_adapter(monkeypatch):
    monkeypatch.setenv("IAT_GOIA_PARTNERSHIP_DELIVERY_ENABLED", "true")

    result = partnership_dispatcher.process_one_delivery()

    assert result["status"] == "blocked"
    assert result["reason"] == "delivery_adapter_not_configured"
    assert result["network_access_performed"] is False
