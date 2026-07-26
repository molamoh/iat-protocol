import sqlite3

import pytest

from iat.goia.contracts import (
    MerchantProviderManifest,
    OfferObservation,
    SearchIntent,
)
import iat.goia.repository as repository
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
