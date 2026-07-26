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
            "review_required": True,
        }
    ]


def test_worker_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("IAT_GOIA_COLLECTION_ENABLED", raising=False)

    assert worker.collection_enabled() is False
    assert worker.main() == 0


def test_worker_never_publishes_candidates_directly(monkeypatch):
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
    assert stats["automatic_publication"] is False


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
        "SELECT provider_id, status, error_code FROM goia_collection_jobs"
    ).fetchone()
    conn.close()

    assert migrated == (None, "failed", "legacy_job_missing_provider")


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
