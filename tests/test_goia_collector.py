import json
import sqlite3

import pytest

import iat.goia.collector as collector
import iat.goia.collector_worker as worker
import iat.goia.repository as repository
from iat.goia.autonomous_review import (
    AUTONOMOUS_REVIEW_POLICY,
    autonomously_review_candidate,
)
from iat.goia.contracts import MerchantProviderManifest, OfferObservation


@pytest.fixture()
def goia_db(tmp_path, monkeypatch):
    database = tmp_path / "goia-collector.db"

    def connect():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(repository, "get_conn", connect)
    monkeypatch.setattr(repository, "release_conn", lambda conn: conn.close())
    monkeypatch.setattr(repository, "qmark", lambda: "?")
    repository.init_goia_tables()
    return database


def _provider():
    return MerchantProviderManifest(
        provider_id="gop_provider_001",
        name="Example Merchant",
        website="https://merchant.example",
        countries=["FR"],
        currencies=["EUR"],
        catalogs=[
            {
                "source_id": "catalog-main",
                "source_type": "sitemap",
                "url": "https://merchant.example/sitemap.xml",
                "refresh_interval_seconds": 3_600,
            }
        ],
    )


def _native_provider():
    return MerchantProviderManifest(
        provider_id="gop_native_001",
        name="Native Merchant",
        website="https://native.example",
        countries=["FR"],
        currencies=["EUR"],
        catalogs=[
            {
                "source_id": "catalog-native",
                "source_type": "goia_json",
                "url": "https://native.example/.well-known/goia-catalog.json",
                "refresh_interval_seconds": 3_600,
            }
        ],
    )


def _review_observation(*, source_sha256="d" * 64):
    return OfferObservation(
        observation_id="goo_reviewed_offer_001",
        offer_id="offer-reviewed-001",
        merchant_id="gop_provider_001",
        kind="software",
        title="Translation API",
        canonical_url="https://merchant.example/product",
        total_price="20.00",
        currency="EUR",
        availability="available",
        observed_at=1_000,
        expires_at=2_000,
        evidence=[
            {
                "source_url": "https://merchant.example/product",
                "extraction_method": "json_ld",
                "content_sha256": source_sha256,
                "observed_at": 1_000,
            }
        ],
        attribute_confidence=90,
    )


class FakeResponse:
    def __init__(
        self,
        body,
        *,
        status_code=200,
        content_type="text/html",
        peer_ip="93.184.216.34",
    ):
        self.body = body if isinstance(body, bytes) else body.encode()
        self.status_code = status_code
        self.peer_ip = peer_ip
        self.headers = {
            "content-type": content_type,
            "content-length": str(len(self.body)),
        }

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url]


@pytest.fixture()
def public_target(monkeypatch):
    monkeypatch.setattr(
        collector,
        "validate_public_runtime_url",
        lambda url: {
            "scheme": "https",
            "hostname": "merchant.example",
            "resolved_addresses": ["93.184.216.34"],
            "public": True,
        },
    )
    return {"merchant.example"}


def test_collection_is_fail_closed_without_allowlist(monkeypatch):
    monkeypatch.delenv("IAT_GOIA_COLLECTION_HOSTS", raising=False)

    with pytest.raises(collector.GOIACollectionError, match="hosts_not_configured"):
        collector.validate_collection_url("https://merchant.example/product")


def test_collection_rejects_host_outside_allowlist(public_target):
    with pytest.raises(collector.GOIACollectionError, match="host_not_allowed"):
        collector.validate_collection_url(
            "https://other.example/product",
            allowed_hosts=public_target,
        )


def test_fetch_never_follows_redirects(public_target):
    session = FakeSession(
        {
            "https://merchant.example/product": FakeResponse(
                b"",
                status_code=302,
            )
        }
    )

    with pytest.raises(collector.GOIACollectionError, match="redirect_not_followed"):
        collector.fetch_document(
            "https://merchant.example/product",
            session=session,
            allowed_hosts=public_target,
        )

    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["stream"] is True


def test_fetch_rejects_dns_rebinding_peer(public_target):
    session = FakeSession(
        {
            "https://merchant.example/product": FakeResponse(
                "unsafe",
                peer_ip="8.8.8.8",
            )
        }
    )

    with pytest.raises(collector.GOIACollectionError, match="resolution_mismatch"):
        collector.fetch_document(
            "https://merchant.example/product",
            session=session,
            allowed_hosts=public_target,
        )


def test_robots_disallow_blocks_page_fetch(public_target):
    session = FakeSession(
        {
            "https://merchant.example/robots.txt": FakeResponse(
                "User-agent: *\nDisallow: /private",
                content_type="text/plain",
            ),
        }
    )

    with pytest.raises(collector.GOIACollectionError, match="robots_disallowed"):
        collector.fetch_allowed_document(
            "https://merchant.example/private/product",
            session=session,
            allowed_hosts=public_target,
        )

    assert [call[0] for call in session.calls] == [
        "https://merchant.example/robots.txt"
    ]


def test_allowed_page_is_bounded_and_hashed(public_target):
    html = "<html><body>safe</body></html>"
    session = FakeSession(
        {
            "https://merchant.example/robots.txt": FakeResponse(
                "User-agent: *\nAllow: /",
                content_type="text/plain",
            ),
            "https://merchant.example/product": FakeResponse(html),
        }
    )

    document = collector.fetch_allowed_document(
        "https://merchant.example/product",
        session=session,
        allowed_hosts=public_target,
    )

    assert document.body == html.encode()
    assert len(document.sha256) == 64


def test_sitemap_rejects_entities_and_cross_domain_urls(public_target):
    unsafe = collector.CollectedDocument(
        url="https://merchant.example/sitemap.xml",
        content_type="application/xml",
        body=b"<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><urlset/>",
        sha256="a" * 64,
    )
    with pytest.raises(collector.GOIACollectionError, match="unsafe_xml"):
        collector.extract_sitemap_urls(unsafe, allowed_hosts=public_target)

    cross_domain = collector.CollectedDocument(
        url="https://merchant.example/sitemap.xml",
        content_type="application/xml",
        body=(
            b"<urlset><url><loc>https://other.example/product</loc></url></urlset>"
        ),
        sha256="b" * 64,
    )
    with pytest.raises(collector.GOIACollectionError, match="host_not_allowed"):
        collector.extract_sitemap_urls(cross_domain, allowed_hosts=public_target)


def test_json_ld_extraction_produces_review_candidates_only():
    payload = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Translation API",
        "url": "https://merchant.example/product",
        "offers": {
            "@type": "Offer",
            "price": "20.00",
            "priceCurrency": "EUR",
        },
    }
    html = (
        "<html><script type=\"application/ld+json\">"
        + json.dumps(payload)
        + "</script></html>"
    ).encode()
    document = collector.CollectedDocument(
        url="https://merchant.example/product",
        content_type="text/html",
        body=html,
        sha256="c" * 64,
    )

    candidates = collector.extract_commercial_json_ld(document)

    assert candidates == [
        {
            "source_url": "https://merchant.example/product",
            "source_sha256": "c" * 64,
            "schema_types": ["SoftwareApplication"],
            "name": "Translation API",
            "url": "https://merchant.example/product",
            "offers": payload["offers"],
            "extraction_method": "json_ld",
            "review_required": True,
        }
    ]


def _native_catalog_document(**updates):
    payload = {
        "contract_version": "goia_catalog_v1",
        "provider_id": "gop_native_001",
        "generated_at": 1_000,
        "expires_at": 2_000,
        "offers": [
            {
                "offer_id": "native-api-plan",
                "kind": "api",
                "title": "Native Translation API",
                "canonical_url": "https://native.example/products/api-plan",
                "total_price": "15.00",
                "currency": "EUR",
                "availability": "available",
            }
        ],
    }
    payload.update(updates)
    body = json.dumps(payload).encode()
    return collector.CollectedDocument(
        url="https://native.example/.well-known/goia-catalog.json",
        content_type="application/json",
        body=body,
        sha256="9" * 64,
    )


def test_native_catalog_is_strict_fresh_and_provider_bound():
    candidates = collector.extract_native_catalog_candidates(
        _native_catalog_document(),
        provider_id="gop_native_001",
        now=1_100,
    )

    assert candidates[0]["goia_kind"] == "api"
    assert candidates[0]["extraction_method"] == "partner_catalog"
    assert candidates[0]["source_sha256"] == "9" * 64

    with pytest.raises(collector.GOIACollectionError, match="provider_mismatch"):
        collector.extract_native_catalog_candidates(
            _native_catalog_document(),
            provider_id="gop_other_001",
            now=1_100,
        )
    with pytest.raises(collector.GOIACollectionError, match="catalog_expired"):
        collector.extract_native_catalog_candidates(
            _native_catalog_document(),
            provider_id="gop_native_001",
            now=2_001,
        )


def test_native_catalog_rejects_offer_on_another_domain():
    document = _native_catalog_document(
        offers=[
            {
                "offer_id": "external-api-plan",
                "kind": "api",
                "title": "External API",
                "canonical_url": "https://other.example/api",
                "total_price": "10.00",
                "currency": "EUR",
                "availability": "available",
            }
        ]
    )

    with pytest.raises(collector.GOIACollectionError, match="offer_domain_mismatch"):
        collector.extract_native_catalog_candidates(
            document,
            provider_id="gop_native_001",
            now=1_100,
        )


def test_worker_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("IAT_GOIA_COLLECTION_ENABLED", raising=False)

    assert worker.collection_enabled() is False
    assert worker.main() == 0


def test_provider_manifest_requires_exact_self_hosted_source():
    provider = MerchantProviderManifest(
        provider_id="gop_provider_001",
        name="Example Merchant",
        website="https://merchant.example",
        countries=["FR"],
        currencies=["EUR"],
        catalogs=[
            {
                "source_id": "catalog-main",
                "source_type": "sitemap",
                "url": "https://merchant.example/sitemap.xml",
                "refresh_interval_seconds": 3_600,
            }
        ],
        partnership_discovery={
            "accepts_partnership_requests": True,
            "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
            "request_endpoint": "https://merchant.example/goia-partnership",
            "relationship_types": ["affiliate"],
        },
    )
    document = collector.CollectedDocument(
        url="https://merchant.example/.well-known/goia-provider.json",
        content_type="application/json",
        body=json.dumps(provider.model_dump(mode="json")).encode(),
        sha256="a" * 64,
    )

    extracted = collector.extract_provider_manifest(
        document,
        provider_id=provider.provider_id,
    )

    assert extracted == provider
    with pytest.raises(collector.GOIACollectionError, match="provider_mismatch"):
        collector.extract_provider_manifest(document, provider_id="gop_other_001")


def test_worker_never_publishes_candidates_directly(monkeypatch):
    monkeypatch.setattr(
        worker,
        "recover_stale_collection_jobs",
        lambda: {"status": "ok", "recovered_count": 0, "exhausted_count": 0},
    )
    monkeypatch.setattr(
        worker,
        "schedule_due_quarantine_retries",
        lambda: {"status": "ok", "scheduled_count": 0, "exhausted_count": 0},
    )
    monkeypatch.setattr(
        worker,
        "seed_due_catalog_sources",
        lambda: {"status": "ok", "seeded_count": 0},
    )
    monkeypatch.setattr(
        worker,
        "refresh_partnership_opportunities",
        lambda: {"status": "ok", "refreshed_count": 0},
    )
    monkeypatch.setattr(worker, "refresh_partner_permissions", lambda: {"status": "ok"})
    monkeypatch.setattr(
        worker,
        "claim_collection_job",
        lambda: {
            "job_id": "goj_test",
            "provider_id": "gop_provider_001",
            "url": "https://merchant.example/product",
        },
    )
    monkeypatch.setattr(
        worker,
        "fetch_allowed_document",
        lambda url: collector.CollectedDocument(
            url=url,
            content_type="text/html",
            body=b"<html/>",
            sha256="d" * 64,
        ),
    )
    monkeypatch.setattr(
        worker,
        "extract_commercial_json_ld",
        lambda document: [{"name": "candidate", "review_required": True}],
    )
    monkeypatch.setattr(worker, "extract_partner_hints", lambda document: [])
    monkeypatch.setattr(
        worker,
        "upsert_partner_hints",
        lambda hints: {"stored_count": 0, "outreach_triggered": False},
    )
    monkeypatch.setattr(worker, "refresh_opportunity_prospect_links", lambda: {})
    completed = {}
    monkeypatch.setattr(
        worker,
        "store_review_candidates",
        lambda **kwargs: ["goc_candidate_001"],
    )
    monkeypatch.setattr(
        worker,
        "autonomously_review_candidate",
        lambda candidate_id: {
            "candidate_id": candidate_id,
            "status": "approved",
        },
    )
    monkeypatch.setattr(
        worker,
        "complete_collection_job",
        lambda job_id, result: completed.update(job_id=job_id, result=result),
    )

    result = worker.process_one_job()

    assert result["publication_status"] == "autonomously_reviewed"
    assert result["approved_count"] == 1
    assert completed["result"]["publication_status"] == "autonomously_reviewed"
    assert completed["result"]["candidate_ids"] == ["goc_candidate_001"]


def test_extracts_partner_hints_without_accessing_discovered_domain():
    payload = {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": "Cloud comparison",
        "offers": [
            {
                "@type": "Offer",
                "price": "12.00",
                "priceCurrency": "EUR",
                "seller": {
                    "@type": "Organization",
                    "name": "Merchant One",
                    "url": "https://merchant-one.example/plans",
                },
            },
            {
                "@type": "Offer",
                "priceCurrency": "EUR",
                "seller": {
                    "name": "Unsafe",
                    "url": "https://user:secret@unsafe.example/path",
                },
            },
        ],
    }
    document = collector.CollectedDocument(
        url="https://comparison.example/cloud",
        content_type="text/html",
        body=(
            b'<script type="application/ld+json">'
            + json.dumps(payload).encode()
            + b"</script>"
        ),
        sha256="a" * 64,
    )

    hints = collector.extract_partner_hints(document)

    assert len(hints) == 1
    assert hints[0]["domain"] == "merchant-one.example"
    assert hints[0]["evidence_type"] == "schema_offer_seller"
    assert hints[0]["kinds"] == ["Service"]
    assert hints[0]["currencies"] == ["EUR"]
    assert hints[0]["network_access_performed"] is False
    assert hints[0]["outreach_authorized"] is False


def test_collection_queue_is_idempotent_and_claimed_once(goia_db):
    repository.upsert_merchant(_provider(), now=900)
    first = repository.enqueue_collection_job(
        provider_id="gop_provider_001",
        url="https://merchant.example/product",
        idempotency_key="collection-key-0001",
        now=1_000,
    )
    duplicate = repository.enqueue_collection_job(
        provider_id="gop_provider_001",
        url="https://merchant.example/product",
        idempotency_key="collection-key-0001",
        now=1_001,
    )

    claimed = repository.claim_collection_job(now=1_010)
    second_claim = repository.claim_collection_job(now=1_011)

    assert first["state"] == "created"
    assert duplicate["job_id"] == first["job_id"]
    assert claimed["job_id"] == first["job_id"]
    assert second_claim is None

    repository.complete_collection_job(
        claimed["job_id"],
        result={"publication_status": "review_required"},
        now=1_020,
    )
    stats = repository.collection_job_stats()
    assert stats["jobs"]["completed"] == 1
    assert stats["collection_direct_publication"] is False
    assert stats["autonomous_policy_publication"] is True


def test_phase_three_collection_jobs_are_migrated_fail_closed(tmp_path, monkeypatch):
    database = tmp_path / "legacy-goia.db"
    conn = sqlite3.connect(database)
    conn.execute(
        """
        CREATE TABLE goia_collection_jobs (
            job_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            url TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            result_json TEXT,
            error_code TEXT,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO goia_collection_jobs (
            job_id, idempotency_key, url, status, attempts, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "goj_legacy",
            "legacy-key",
            "https://merchant.example/product",
            "queued",
            0,
            900,
            900,
        ),
    )
    conn.commit()
    conn.close()

    def connect():
        opened = sqlite3.connect(database)
        opened.row_factory = sqlite3.Row
        return opened

    monkeypatch.setattr(repository, "get_conn", connect)
    monkeypatch.setattr(repository, "release_conn", lambda opened: opened.close())
    monkeypatch.setattr(repository, "qmark", lambda: "?")
    repository.init_goia_tables()

    conn = sqlite3.connect(database)
    migrated = conn.execute(
        """
        SELECT provider_id, job_type, parent_job_id, priority, status, error_code
        FROM goia_collection_jobs
        """
    ).fetchone()
    conn.close()

    assert migrated == (
        None,
        "page",
        None,
        50,
        "failed",
        "legacy_job_missing_provider",
    )


def _pending_candidate():
    return {
        "source_url": "https://merchant.example/product",
        "source_sha256": "d" * 64,
        "schema_types": ["SoftwareApplication"],
        "name": "Translation API",
        "url": "https://merchant.example/product",
        "offers": {"price": "20.00", "priceCurrency": "EUR"},
        "review_required": True,
    }


def _autonomous_candidate(**offer_updates):
    offer = {
        "@type": "Offer",
        "price": "20.00",
        "priceCurrency": "EUR",
        "availability": "https://schema.org/InStock",
    }
    offer.update(offer_updates)
    return {
        "source_url": "https://merchant.example/product",
        "source_sha256": "d" * 64,
        "schema_types": ["SoftwareApplication"],
        "name": "Translation API",
        "url": "https://merchant.example/product",
        "offers": offer,
        "review_required": True,
    }


def _create_pending_candidate():
    repository.upsert_merchant(_provider(), now=900)
    job = repository.enqueue_collection_job(
        provider_id="gop_provider_001",
        url="https://merchant.example/product",
        idempotency_key="review-job-key-0001",
        now=950,
    )
    claimed = repository.claim_collection_job(now=960)
    assert claimed["job_id"] == job["job_id"]
    candidate_ids = repository.store_review_candidates(
        job_id=job["job_id"],
        provider_id="gop_provider_001",
        candidates=[_pending_candidate()],
        now=970,
    )
    return candidate_ids[0]


def test_review_candidate_requires_exact_collected_evidence(goia_db):
    candidate_id = _create_pending_candidate()

    with pytest.raises(repository.GOIARepositoryError, match="evidence_mismatch"):
        repository.approve_review_candidate(
            candidate_id,
            observation=_review_observation(source_sha256="e" * 64),
            reviewer="foundation-reviewer",
            reason="Verified offer fields against the collected page.",
            now=1_000,
        )

    assert repository.goia_index_stats(now=1_100)["observations"] == 0


def test_approved_candidate_is_published_once(goia_db):
    candidate_id = _create_pending_candidate()
    observation = _review_observation()

    approved = repository.approve_review_candidate(
        candidate_id,
        observation=observation,
        reviewer="foundation-reviewer",
        reason="Verified offer fields against the collected page.",
        now=1_000,
    )
    duplicate = repository.approve_review_candidate(
        candidate_id,
        observation=observation,
        reviewer="foundation-reviewer",
        reason="Verified offer fields against the collected page.",
        now=1_001,
    )

    assert approved["state"] == "approved"
    assert duplicate["state"] == "duplicate"
    assert repository.goia_index_stats(now=1_100)["observations"] == 1
    reviewed = repository.list_review_candidates(status="approved")
    assert reviewed["items"][0]["raw"]["review_required"] is True
    assert reviewed["items"][0]["normalized"]["observation_id"] == observation.observation_id


def test_rejected_candidate_never_reaches_index(goia_db):
    candidate_id = _create_pending_candidate()

    rejected = repository.reject_review_candidate(
        candidate_id,
        reviewer="foundation-reviewer",
        reason="Price could not be verified from the collected evidence.",
        now=1_000,
    )
    duplicate = repository.reject_review_candidate(
        candidate_id,
        reviewer="foundation-reviewer",
        reason="Price could not be verified from the collected evidence.",
        now=1_001,
    )

    assert rejected["state"] == "rejected"
    assert duplicate["state"] == "duplicate"
    assert repository.goia_index_stats(now=1_100)["observations"] == 0


def test_autonomous_review_publishes_complete_structured_offer(goia_db):
    repository.upsert_merchant(_provider(), now=900)
    job = repository.enqueue_collection_job(
        provider_id="gop_provider_001",
        url="https://merchant.example/product",
        idempotency_key="autonomous-job-key-0001",
        now=950,
    )
    repository.claim_collection_job(now=960)
    candidate_id = repository.store_review_candidates(
        job_id=job["job_id"],
        provider_id="gop_provider_001",
        candidates=[_autonomous_candidate()],
        now=1_000,
    )[0]

    result = autonomously_review_candidate(candidate_id)

    assert result["status"] == "approved"
    assert result["policy"] == AUTONOMOUS_REVIEW_POLICY
    assert repository.goia_index_stats(now=1_100)["observations"] == 1
    approved = repository.list_review_candidates(status="approved")["items"][0]
    assert approved["reviewer"] == AUTONOMOUS_REVIEW_POLICY
    assert approved["reason"] == "deterministic_policy_and_exact_evidence_passed"


def test_autonomous_review_quarantines_incomplete_offer_without_human(goia_db):
    repository.upsert_merchant(_provider(), now=900)
    job = repository.enqueue_collection_job(
        provider_id="gop_provider_001",
        url="https://merchant.example/product",
        idempotency_key="autonomous-job-key-0002",
        now=950,
    )
    repository.claim_collection_job(now=960)
    candidate_id = repository.store_review_candidates(
        job_id=job["job_id"],
        provider_id="gop_provider_001",
        candidates=[_autonomous_candidate(availability=None)],
        now=1_000,
    )[0]

    result = autonomously_review_candidate(candidate_id)
    duplicate = autonomously_review_candidate(candidate_id)

    assert result["status"] == "quarantined"
    assert result["reason"] == "recognized_availability_required"
    assert duplicate["state"] == "already_quarantined"
    assert repository.goia_index_stats(now=1_100)["observations"] == 0


def test_quarantine_retries_use_bounded_exponential_backoff(goia_db):
    repository.upsert_merchant(_provider(), now=900)
    job = repository.enqueue_collection_job(
        provider_id="gop_provider_001",
        url="https://merchant.example/product",
        idempotency_key="retry-source-job-0001",
        now=950,
    )
    repository.claim_collection_job(now=960)
    candidate_id = repository.store_review_candidates(
        job_id=job["job_id"],
        provider_id="gop_provider_001",
        candidates=[_autonomous_candidate(availability=None)],
        now=1_000,
    )[0]
    repository.quarantine_review_candidate(
        candidate_id,
        policy=AUTONOMOUS_REVIEW_POLICY,
        reason="recognized_availability_required",
        now=1_000,
    )

    first = repository.schedule_due_quarantine_retries(now=4_600)
    second = repository.schedule_due_quarantine_retries(now=11_800)
    third = repository.schedule_due_quarantine_retries(now=26_200)
    exhausted = repository.schedule_due_quarantine_retries(now=55_000)

    assert first["scheduled"][0]["retry_count"] == 1
    assert first["scheduled"][0]["next_retry_at"] == 11_800
    assert second["scheduled"][0]["retry_count"] == 2
    assert third["scheduled"][0]["retry_count"] == 3
    assert exhausted["exhausted"] == [candidate_id]
    final = repository.list_review_candidates(status="quarantine_exhausted")
    assert final["count"] == 1


def test_stale_worker_leases_are_recovered_then_exhausted(goia_db):
    repository.upsert_merchant(_provider(), now=900)
    repository.enqueue_collection_job(
        provider_id="gop_provider_001",
        url="https://merchant.example/product",
        idempotency_key="stale-job-key-0001",
        now=950,
    )

    first = repository.claim_collection_job(now=1_000)
    recovered_one = repository.recover_stale_collection_jobs(
        now=1_400,
        lease_seconds=300,
    )
    second = repository.claim_collection_job(now=1_500)
    recovered_two = repository.recover_stale_collection_jobs(
        now=1_900,
        lease_seconds=300,
    )
    third = repository.claim_collection_job(now=2_000)
    exhausted = repository.recover_stale_collection_jobs(
        now=2_400,
        lease_seconds=300,
    )

    assert first["attempts"] == 1
    assert second["attempts"] == 2
    assert third["attempts"] == 3
    assert recovered_one["recovered_count"] == 1
    assert recovered_two["recovered_count"] == 1
    assert exhausted["exhausted_count"] == 1
    assert repository.collection_job_stats()["jobs"]["failed"] == 1


def test_catalog_sources_seed_once_per_refresh_window(goia_db):
    repository.upsert_merchant(_provider(), now=900)

    first = repository.seed_due_catalog_sources(now=7_200)
    duplicate = repository.seed_due_catalog_sources(now=7_201)
    next_window = repository.seed_due_catalog_sources(now=10_800)

    assert first["seeded_count"] == 1
    assert duplicate["seeded_count"] == 0
    assert next_window["seeded_count"] == 1
    claimed = repository.claim_collection_job(now=10_801)
    assert claimed["job_type"] == "sitemap"
    assert claimed["priority"] == 100


def test_native_catalog_source_is_seeded_below_sitemap_priority(goia_db):
    repository.upsert_merchant(_provider(), now=900)
    repository.upsert_merchant(_native_provider(), now=900)

    seeded = repository.seed_due_catalog_sources(now=7_200)
    first = repository.claim_collection_job(now=7_201)
    repository.complete_collection_job(first["job_id"], result={}, now=7_202)
    second = repository.claim_collection_job(now=7_203)

    assert seeded["seeded_count"] == 2
    assert first["job_type"] == "sitemap"
    assert first["priority"] == 100
    assert second["job_type"] == "catalog_json"
    assert second["priority"] == 90


def test_partnership_manifest_source_is_seeded_for_periodic_verification(goia_db):
    provider = MerchantProviderManifest(
        **{
            **_provider().model_dump(mode="json"),
            "partnership_discovery": {
                "accepts_partnership_requests": True,
                "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
                "request_endpoint": "https://merchant.example/goia-partnership",
                "relationship_types": ["affiliate"],
                "verification_interval_seconds": 3_600,
            },
        }
    )
    repository.upsert_merchant(provider, now=900)

    seeded = repository.seed_due_catalog_sources(now=7_200)
    first = repository.claim_collection_job(now=7_201)

    assert seeded["seeded_count"] == 2
    assert first["job_type"] == "sitemap"
    repository.complete_collection_job(first["job_id"], result={}, now=7_202)
    verification = repository.claim_collection_job(now=7_203)
    assert verification["job_type"] == "provider_manifest"
    assert verification["priority"] == 95


def test_native_catalog_flows_through_autonomous_publication(goia_db):
    provider = _native_provider()
    repository.upsert_merchant(provider, now=900)
    job = repository.enqueue_collection_job(
        provider_id=provider.provider_id,
        url="https://native.example/.well-known/goia-catalog.json",
        idempotency_key="native-catalog-job-0001",
        job_type="catalog_json",
        priority=90,
        now=1_050,
    )
    repository.claim_collection_job(now=1_060)
    candidates = collector.extract_native_catalog_candidates(
        _native_catalog_document(),
        provider_id=provider.provider_id,
        now=1_100,
    )
    candidate_id = repository.store_review_candidates(
        job_id=job["job_id"],
        provider_id=provider.provider_id,
        candidates=candidates,
        now=1_100,
    )[0]

    decision = autonomously_review_candidate(candidate_id)

    assert decision["status"] == "approved"
    approved = repository.list_review_candidates(status="approved")["items"][0]
    assert approved["normalized"]["kind"] == "api"
    assert approved["normalized"]["offer_id"] == "native-api-plan"
    assert approved["normalized"]["expires_at"] == 2_000
    assert approved["normalized"]["evidence"][0]["extraction_method"] == "partner_catalog"


def test_sitemap_pages_are_bounded_parented_and_idempotent(goia_db):
    repository.upsert_merchant(_provider(), now=900)
    seeded = repository.seed_due_catalog_sources(now=7_200)
    sitemap = repository.claim_collection_job(now=7_201)
    assert sitemap["job_id"] == seeded["seeded"][0]["job_id"]
    urls = [
        f"https://merchant.example/product-{index}"
        for index in range(150)
    ]

    first = repository.enqueue_sitemap_pages(
        sitemap_job=sitemap,
        urls=urls,
        now=7_202,
        limit=100,
    )
    duplicate = repository.enqueue_sitemap_pages(
        sitemap_job=sitemap,
        urls=urls,
        now=7_203,
        limit=100,
    )

    assert first["created_count"] == 100
    assert first["truncated"] is True
    assert duplicate["created_count"] == 0
    assert duplicate["duplicate_count"] == 100
    page = repository.claim_collection_job(now=7_204)
    assert page["job_type"] == "page"
    assert page["parent_job_id"] == sitemap["job_id"]
    assert page["priority"] == 50


def test_worker_expands_sitemap_without_treating_it_as_product(monkeypatch):
    maintenance = {"status": "ok"}
    monkeypatch.setattr(worker, "recover_stale_collection_jobs", lambda: maintenance)
    monkeypatch.setattr(worker, "schedule_due_quarantine_retries", lambda: maintenance)
    monkeypatch.setattr(worker, "seed_due_catalog_sources", lambda: maintenance)
    monkeypatch.setattr(
        worker,
        "refresh_partnership_opportunities",
        lambda: maintenance,
    )
    monkeypatch.setattr(worker, "refresh_partner_permissions", lambda: maintenance)
    monkeypatch.setattr(
        worker,
        "claim_collection_job",
        lambda: {
            "job_id": "goj_sitemap",
            "provider_id": "gop_provider_001",
            "url": "https://merchant.example/sitemap.xml",
            "job_type": "sitemap",
        },
    )
    monkeypatch.setattr(
        worker,
        "fetch_allowed_document",
        lambda url: collector.CollectedDocument(
            url=url,
            content_type="application/xml",
            body=b"<urlset/>",
            sha256="f" * 64,
        ),
    )
    monkeypatch.setattr(
        worker,
        "extract_sitemap_urls",
        lambda document: [
            "https://merchant.example/product-1",
            "https://merchant.example/product-2",
        ],
    )
    monkeypatch.setattr(
        worker,
        "enqueue_sitemap_pages",
        lambda **kwargs: {
            "created_count": 2,
            "duplicate_count": 0,
            "job_ids": ["goj_page_1", "goj_page_2"],
        },
    )
    completed = {}
    monkeypatch.setattr(
        worker,
        "complete_collection_job",
        lambda job_id, result: completed.update(job_id=job_id, result=result),
    )

    result = worker.process_one_job()

    assert result["job_type"] == "sitemap"
    assert result["discovered_url_count"] == 2
    assert result["page_jobs_created"] == 2
    assert completed["result"]["publication_status"] == "discovery_only"


def test_worker_verifies_provider_manifest_without_creating_offer(monkeypatch):
    maintenance = {"status": "ok"}
    provider = MerchantProviderManifest(
        provider_id="gop_provider_001",
        name="Example Merchant",
        website="https://merchant.example",
        countries=["FR"],
        currencies=["EUR"],
        catalogs=[
            {
                "source_id": "catalog-main",
                "source_type": "sitemap",
                "url": "https://merchant.example/sitemap.xml",
                "refresh_interval_seconds": 3_600,
            }
        ],
        partnership_discovery={
            "accepts_partnership_requests": True,
            "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
            "request_endpoint": "https://merchant.example/goia-partnership",
            "relationship_types": ["affiliate"],
        },
    )
    monkeypatch.setattr(worker, "recover_stale_collection_jobs", lambda: maintenance)
    monkeypatch.setattr(worker, "schedule_due_quarantine_retries", lambda: maintenance)
    monkeypatch.setattr(worker, "seed_due_catalog_sources", lambda: maintenance)
    monkeypatch.setattr(worker, "refresh_partnership_opportunities", lambda: maintenance)
    permission_results = iter([maintenance, {"verified_opt_in_count": 1}])
    monkeypatch.setattr(
        worker,
        "refresh_partner_permissions",
        lambda: next(permission_results),
    )
    monkeypatch.setattr(
        worker,
        "claim_collection_job",
        lambda: {
            "job_id": "goj_manifest",
            "provider_id": provider.provider_id,
            "url": str(provider.partnership_discovery.manifest_url),
            "job_type": "provider_manifest",
        },
    )
    document = collector.CollectedDocument(
        url=str(provider.partnership_discovery.manifest_url),
        content_type="application/json",
        body=json.dumps(provider.model_dump(mode="json")).encode(),
        sha256="b" * 64,
    )
    monkeypatch.setattr(worker, "fetch_allowed_document", lambda url: document)
    monkeypatch.setattr(
        worker,
        "extract_provider_manifest",
        lambda document, provider_id: provider,
    )
    monkeypatch.setattr(
        worker,
        "record_provider_manifest_verification",
        lambda **kwargs: {"status": "verified", "outreach_triggered": False},
    )
    completed = {}
    monkeypatch.setattr(
        worker,
        "complete_collection_job",
        lambda job_id, result: completed.update(job_id=job_id, result=result),
    )

    result = worker.process_one_job()

    assert result["job_type"] == "provider_manifest"
    assert result["publication_status"] == "verification_only"
    assert result["outreach_triggered"] is False
    assert completed["result"]["publication_status"] == "verification_only"
    assert "candidate_count" not in completed["result"]
