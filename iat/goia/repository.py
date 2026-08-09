"""Persistence for the isolated GOIA commercial index."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from iat.api.db import get_conn, qmark, release_conn
from iat.goia.contracts import (
    MerchantProviderManifest,
    OfferObservation,
    PartnershipAcknowledgement,
    PartnershipProposal,
)


class GOIARepositoryError(ValueError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode()).hexdigest()


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _ensure_column(conn, cur, table: str, column: str, definition: str):
    try:
        cur.execute(f"SELECT {column} FROM {table} LIMIT 0")
        return cur
    except Exception:
        conn.rollback()
        migrated = conn.cursor()
        migrated.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        return migrated


def init_goia_tables() -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_merchants (
                provider_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                website TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_external_prospects (
                prospect_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'discovered',
                observed_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(source_id, source_url)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_external_prospect_reviews (
                review_id TEXT PRIMARY KEY,
                prospect_id TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(prospect_id, reviewer, created_at)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_offer_observations (
                observation_id TEXT PRIMARY KEY,
                offer_id TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                total_price TEXT NOT NULL,
                currency TEXT NOT NULL,
                availability TEXT NOT NULL,
                observed_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                attribute_confidence INTEGER NOT NULL,
                commercial_relationship TEXT NOT NULL,
                sponsored INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                ingested_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_goia_offer_lookup
            ON goia_offer_observations(
                kind, currency, availability, expires_at, observed_at
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_goia_offer_merchant
            ON goia_offer_observations(merchant_id, offer_id, observed_at)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_collection_jobs (
                job_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                provider_id TEXT NOT NULL,
                url TEXT NOT NULL,
                job_type TEXT NOT NULL DEFAULT 'page',
                parent_job_id TEXT,
                priority INTEGER NOT NULL DEFAULT 50,
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
        cur = _ensure_column(
            conn,
            cur,
            "goia_collection_jobs",
            "provider_id",
            "TEXT",
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_collection_jobs",
            "job_type",
            "TEXT NOT NULL DEFAULT 'page'",
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_collection_jobs",
            "parent_job_id",
            "TEXT",
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_collection_jobs",
            "priority",
            "INTEGER NOT NULL DEFAULT 50",
        )
        cur.execute(
            """
            UPDATE goia_collection_jobs
            SET status = 'failed',
                error_code = 'legacy_job_missing_provider'
            WHERE provider_id IS NULL
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_review_candidates (
                candidate_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                raw_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                normalized_json TEXT,
                reviewer TEXT,
                reason TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at INTEGER,
                last_retry_job_id TEXT,
                created_at INTEGER NOT NULL,
                reviewed_at INTEGER,
                updated_at INTEGER NOT NULL,
                UNIQUE(job_id, raw_hash)
            )
            """
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_review_candidates",
            "retry_count",
            "INTEGER NOT NULL DEFAULT 0",
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_review_candidates",
            "next_retry_at",
            "INTEGER",
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_review_candidates",
            "last_retry_job_id",
            "TEXT",
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_goia_review_candidates_status
            ON goia_review_candidates(status, created_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_goia_collection_jobs_status
            ON goia_collection_jobs(status, created_at)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_demand_signals (
                signal_key TEXT PRIMARY KEY,
                period_day INTEGER NOT NULL,
                query_fingerprint TEXT NOT NULL,
                kind TEXT NOT NULL,
                country TEXT NOT NULL,
                currency TEXT NOT NULL,
                request_count INTEGER NOT NULL,
                satisfied_count INTEGER NOT NULL,
                unmet_count INTEGER NOT NULL,
                matched_result_count INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_goia_demand_period_market
            ON goia_demand_signals(period_day, kind, country, currency)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_partnership_opportunities (
                opportunity_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                country TEXT NOT NULL,
                currency TEXT NOT NULL,
                demand_count INTEGER NOT NULL,
                unmet_count INTEGER NOT NULL,
                current_offer_count INTEGER NOT NULL,
                gap_score INTEGER NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(kind, country, currency)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_partner_prospects (
                prospect_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                relevance_score INTEGER NOT NULL,
                evidence_count INTEGER NOT NULL,
                signals_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                permission_status TEXT NOT NULL DEFAULT 'none',
                permission_provider_id TEXT,
                permission_evidence_json TEXT,
                outreach_authorized INTEGER NOT NULL DEFAULT 0,
                contact_attempted INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_partner_prospects",
            "permission_status",
            "TEXT NOT NULL DEFAULT 'none'",
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_partner_prospects",
            "permission_provider_id",
            "TEXT",
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_partner_prospects",
            "permission_evidence_json",
            "TEXT",
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_opportunity_prospects (
                opportunity_id TEXT NOT NULL,
                prospect_id TEXT NOT NULL,
                match_score INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(opportunity_id, prospect_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_provider_verifications (
                provider_id TEXT PRIMARY KEY,
                manifest_hash TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                verified_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_partnership_outbox (
                proposal_id TEXT PRIMARY KEY,
                opportunity_id TEXT NOT NULL,
                prospect_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at INTEGER NOT NULL DEFAULT 0,
                lease_token TEXT,
                lease_until INTEGER,
                last_error_code TEXT,
                receipt_json TEXT,
                delivered_at INTEGER,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(opportunity_id, prospect_id, manifest_hash)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_partnership_suppressions (
                domain TEXT PRIMARY KEY,
                provider_id TEXT,
                proposal_id TEXT,
                reason_code TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_partnership_responses (
                response_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                signature TEXT NOT NULL,
                signing_public_key TEXT NOT NULL,
                received_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_partnership_relationships (
                provider_id TEXT NOT NULL,
                prospect_id TEXT NOT NULL,
                latest_proposal_id TEXT NOT NULL,
                latest_response_id TEXT NOT NULL,
                status TEXT NOT NULL,
                terms_url TEXT,
                commission_activated INTEGER NOT NULL DEFAULT 0,
                ranking_effect INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(provider_id, prospect_id)
            )
            """
        )
        for column, definition in (
            ("attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("next_attempt_at", "INTEGER NOT NULL DEFAULT 0"),
            ("lease_token", "TEXT"),
            ("lease_until", "INTEGER"),
            ("last_error_code", "TEXT"),
            ("receipt_json", "TEXT"),
            ("delivered_at", "INTEGER"),
        ):
            cur = _ensure_column(
                conn,
                cur,
                "goia_partnership_outbox",
                column,
                definition,
            )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_partnership_delivery_events (
                event_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                event_order INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                reason TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goia_worker_heartbeats (
                worker_id TEXT PRIMARY KEY,
                worker_type TEXT NOT NULL,
                status TEXT NOT NULL,
                cycle_count INTEGER NOT NULL DEFAULT 0,
                last_result_json TEXT,
                last_error_code TEXT,
                started_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur = _ensure_column(
            conn,
            cur,
            "goia_partnership_delivery_events",
            "event_order",
            "INTEGER NOT NULL DEFAULT 0",
        )
        conn.commit()
    finally:
        release_conn(conn)


def upsert_external_prospect(prospect: dict[str, Any], *, now: int | None = None) -> dict[str, Any]:
    timestamp = int(now or time.time())
    payload_json = _canonical_json(prospect)
    payload_hash = _payload_hash(payload_json)
    source_id = str(prospect["source_id"])
    source_url = str(prospect["source_url"])
    prospect_id = f"gxp_{hashlib.sha256(f'{source_id}:{source_url}'.encode()).hexdigest()[:32]}"
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            INSERT INTO goia_external_prospects
                (prospect_id, source_id, source_url, name, description,
                 payload_json, payload_hash, status, observed_at, updated_at)
            VALUES ({', '.join([marker] * 10)})
            ON CONFLICT(source_id, source_url) DO UPDATE SET
                name = excluded.name, description = excluded.description,
                payload_json = excluded.payload_json, payload_hash = excluded.payload_hash,
                observed_at = excluded.observed_at, updated_at = excluded.updated_at
            """,
            (prospect_id, source_id, source_url, str(prospect.get("name") or "")[:240],
             str(prospect.get("description") or "")[:2000], payload_json, payload_hash,
             "discovered", timestamp, timestamp),
        )
        conn.commit()
        return {"prospect_id": prospect_id, "state": "stored", "source_id": source_id}
    finally:
        release_conn(conn)


def external_prospect_stats() -> dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS count FROM goia_external_prospects")
    count = int(cur.fetchone()["count"])
    release_conn(conn)
    return {"count": count}


def list_external_prospects(
    *, status: str | None = None, limit: int = 100
) -> dict[str, Any]:
    """Return bounded metadata for passive prospect review; never activates a provider."""
    marker = qmark()
    safe_limit = max(1, min(int(limit), 200))
    conn = get_conn()
    cur = conn.cursor()
    try:
        params: list[Any] = []
        where = ""
        if status:
            where = f"WHERE status = {marker}"
            params.append(status.strip()[:80])
        params.append(safe_limit)
        cur.execute(
            f"""
            SELECT prospect_id, source_id, source_url, name, description,
                   status, observed_at, updated_at
            FROM goia_external_prospects
            {where}
            ORDER BY updated_at DESC
            LIMIT {marker}
            """,
            tuple(params),
        )
        return {
            "status": "ok",
            "prospects": [dict(row) for row in cur.fetchall()],
            "provider_activation": False,
        }
    finally:
        release_conn(conn)


def external_prospect_review_queue(*, limit: int = 100) -> dict[str, Any]:
    """Build an explainable, read-only governance queue for qualified prospects."""
    result = list_external_prospects(status="candidate_qualified", limit=limit)
    reviewed: list[dict[str, Any]] = []
    for prospect in result["prospects"]:
        score = 0
        reasons: list[str] = []
        source_id = str(prospect.get("source_id") or "")
        source_url = str(prospect.get("source_url") or "")
        description = str(prospect.get("description") or "")
        if source_id in {"github_public_repositories", "huggingface_spaces"}:
            score += 40
            reasons.append("known_public_registry")
        if source_url.startswith("https://"):
            score += 30
            reasons.append("https_source")
        if len(description.strip()) >= 40:
            score += 20
            reasons.append("descriptive_metadata")
        if len(str(prospect.get("name") or "").strip()) >= 3:
            score += 10
            reasons.append("named_project")
        reviewed.append({
            **prospect,
            "governance_score": score,
            "governance_reasons": reasons,
            "recommendation": "governance_review_required",
            "provider_activation": False,
        })
    return {
        "status": "ok",
        "prospects": reviewed,
        "governance_required": True,
        "provider_activation": False,
    }


def decide_external_prospect(
    prospect_id: str, *, reviewer: str, decision: str, reason: str
) -> dict[str, Any]:
    """Record a governance decision without activating a provider."""
    allowed = {"approve", "reject", "needs_more_evidence"}
    if decision not in allowed:
        raise GOIARepositoryError("invalid_governance_decision")
    now = int(time.time())
    next_status = {
        "approve": "governance_approved",
        "reject": "governance_rejected",
        "needs_more_evidence": "governance_evidence_required",
    }[decision]
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT prospect_id, status FROM goia_external_prospects WHERE prospect_id = "
            + qmark(),
            (prospect_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise GOIARepositoryError("external_prospect_not_found")
        review_id = f"gpr_{uuid.uuid4().hex}"
        marker = qmark()
        cur.execute(
            f"INSERT INTO goia_external_prospect_reviews "
            f"(review_id, prospect_id, reviewer, decision, reason, created_at) "
            f"VALUES ({', '.join([marker] * 6)})",
            (review_id, prospect_id, reviewer.strip()[:120], decision, reason.strip()[:1000], now),
        )
        cur.execute(
            f"UPDATE goia_external_prospects SET status = {marker}, updated_at = {marker} "
            f"WHERE prospect_id = {marker}",
            (next_status, now, prospect_id),
        )
        conn.commit()
        return {
            "status": "recorded",
            "review_id": review_id,
            "prospect_id": prospect_id,
            "decision": decision,
            "prospect_status": next_status,
            "provider_activation": False,
        }
    finally:
        release_conn(conn)


def qualify_external_prospects(limit: int = 50) -> dict[str, Any]:
    """Apply a conservative metadata-only qualification; never activates a provider."""
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    safe_limit = max(1, min(int(limit), 200))
    try:
        cur.execute(
            f"""
            SELECT prospect_id FROM goia_external_prospects
            WHERE status = 'discovered'
              AND length(trim(name)) >= 3
              AND length(trim(source_url)) >= 12
            ORDER BY observed_at ASC
            LIMIT {marker}
            """,
            (safe_limit,),
        )
        ids = [row["prospect_id"] for row in cur.fetchall()]
        for prospect_id in ids:
            cur.execute(
                f"UPDATE goia_external_prospects SET status = 'candidate_qualified', updated_at = {marker} WHERE prospect_id = {marker}",
                (int(time.time()), prospect_id),
            )
        conn.commit()
        return {"status": "ok", "qualified_count": len(ids), "provider_activation": False}
    finally:
        release_conn(conn)


def record_worker_heartbeat(
    *,
    worker_id: str,
    worker_type: str,
    status: str,
    cycle_count: int,
    result: dict[str, Any] | None = None,
    error_code: str | None = None,
    started_at: int | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if status not in {"starting", "idle", "working", "degraded"}:
        raise GOIARepositoryError("invalid_worker_status")
    normalized_id = str(worker_id).strip()
    normalized_type = str(worker_type).strip()
    if not normalized_id or len(normalized_id) > 160:
        raise GOIARepositoryError("invalid_worker_id")
    if not normalized_type or len(normalized_type) > 80:
        raise GOIARepositoryError("invalid_worker_type")
    timestamp = int(now or time.time())
    initial_timestamp = int(started_at or timestamp)
    marker = qmark()
    result_json = _canonical_json(result) if result is not None else None
    bounded_error = str(error_code)[:160] if error_code else None
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT started_at FROM goia_worker_heartbeats WHERE worker_id = {marker}",
            (normalized_id,),
        )
        existing = _row(cur.fetchone())
        if existing is None:
            cur.execute(
                f"""
                INSERT INTO goia_worker_heartbeats (
                    worker_id, worker_type, status, cycle_count,
                    last_result_json, last_error_code, started_at,
                    last_seen_at, updated_at
                ) VALUES ({", ".join([marker] * 9)})
                """,
                (
                    normalized_id,
                    normalized_type,
                    status,
                    max(0, int(cycle_count)),
                    result_json,
                    bounded_error,
                    initial_timestamp,
                    timestamp,
                    timestamp,
                ),
            )
        else:
            cur.execute(
                f"""
                UPDATE goia_worker_heartbeats
                SET worker_type = {marker}, status = {marker},
                    cycle_count = {marker}, last_result_json = {marker},
                    last_error_code = {marker}, last_seen_at = {marker},
                    updated_at = {marker}
                WHERE worker_id = {marker}
                """,
                (
                    normalized_type,
                    status,
                    max(0, int(cycle_count)),
                    result_json,
                    bounded_error,
                    timestamp,
                    timestamp,
                    normalized_id,
                ),
            )
        conn.commit()
        return {
            "worker_id": normalized_id,
            "worker_type": normalized_type,
            "status": status,
            "cycle_count": max(0, int(cycle_count)),
            "last_seen_at": timestamp,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def list_worker_health(
    *,
    stale_after_seconds: int = 180,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    stale_after = max(15, min(int(stale_after_seconds), 3_600))
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT worker_id, worker_type, status, cycle_count,
                   last_result_json, last_error_code, started_at, last_seen_at
            FROM goia_worker_heartbeats
            ORDER BY worker_type ASC, worker_id ASC
            """
        )
        workers = []
        for raw in cur.fetchall():
            row = dict(raw)
            result_json = row.pop("last_result_json", None)
            age = max(0, timestamp - int(row["last_seen_at"]))
            reported_status = str(row["status"])
            operational_status = (
                "stale"
                if age > stale_after
                else ("degraded" if reported_status == "degraded" else "healthy")
            )
            workers.append(
                {
                    **row,
                    "last_result": json.loads(result_json) if result_json else None,
                    "age_seconds": age,
                    "operational_status": operational_status,
                }
            )
        return {
            "status": "ok",
            "as_of": timestamp,
            "stale_after_seconds": stale_after,
            "worker_count": len(workers),
            "healthy_count": sum(
                item["operational_status"] == "healthy" for item in workers
            ),
            "degraded_count": sum(
                item["operational_status"] == "degraded" for item in workers
            ),
            "stale_count": sum(
                item["operational_status"] == "stale" for item in workers
            ),
            "workers": workers,
        }
    finally:
        release_conn(conn)


def upsert_merchant(manifest: MerchantProviderManifest, *, now: int | None = None) -> dict[str, Any]:
    timestamp = int(now or time.time())
    payload = manifest.model_dump(mode="json")
    payload_json = _canonical_json(payload)
    manifest_hash = _payload_hash(payload_json)
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT * FROM goia_merchants WHERE provider_id = {marker}",
            (manifest.provider_id,),
        )
        existing = _row(cur.fetchone())
        if existing is None:
            cur.execute(
                f"""
                INSERT INTO goia_merchants (
                    provider_id, name, website, manifest_json, manifest_hash,
                    created_at, updated_at
                ) VALUES ({", ".join([marker] * 7)})
                """,
                (
                    manifest.provider_id,
                    manifest.name,
                    str(manifest.website),
                    payload_json,
                    manifest_hash,
                    timestamp,
                    timestamp,
                ),
            )
            state = "created"
        elif existing["manifest_hash"] == manifest_hash:
            state = "unchanged"
        else:
            cur.execute(
                f"""
                UPDATE goia_merchants
                SET name = {marker}, website = {marker}, manifest_json = {marker},
                    manifest_hash = {marker}, updated_at = {marker}
                WHERE provider_id = {marker}
                """,
                (
                    manifest.name,
                    str(manifest.website),
                    payload_json,
                    manifest_hash,
                    timestamp,
                    manifest.provider_id,
                ),
            )
            state = "updated"
        conn.commit()
        return {
            "provider_id": manifest.provider_id,
            "state": state,
            "manifest_hash": manifest_hash,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def ingest_observation(
    observation: OfferObservation,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    payload = observation.model_dump(mode="json")
    payload_json = _canonical_json(payload)
    payload_hash = _payload_hash(payload_json)
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT payload_hash FROM goia_offer_observations WHERE observation_id = {marker}",
            (observation.observation_id,),
        )
        existing = _row(cur.fetchone())
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                raise GOIARepositoryError("observation_id_payload_conflict")
            return {
                "observation_id": observation.observation_id,
                "state": "duplicate",
                "payload_hash": payload_hash,
            }

        cur.execute(
            f"SELECT provider_id FROM goia_merchants WHERE provider_id = {marker}",
            (observation.merchant_id,),
        )
        if cur.fetchone() is None:
            raise GOIARepositoryError("merchant_not_found")

        cur.execute(
            f"""
            INSERT INTO goia_offer_observations (
                observation_id, offer_id, merchant_id, kind, title,
                canonical_url, total_price, currency, availability,
                observed_at, expires_at, attribute_confidence,
                commercial_relationship, sponsored, payload_json,
                payload_hash, ingested_at
            ) VALUES ({", ".join([marker] * 17)})
            """,
            (
                observation.observation_id,
                observation.offer_id,
                observation.merchant_id,
                observation.kind,
                observation.title,
                str(observation.canonical_url),
                observation.total_price,
                observation.currency,
                observation.availability,
                observation.observed_at,
                observation.expires_at,
                observation.attribute_confidence,
                observation.commercial_relationship,
                int(observation.sponsored),
                payload_json,
                payload_hash,
                timestamp,
            ),
        )
        conn.commit()
        return {
            "observation_id": observation.observation_id,
            "state": "created",
            "payload_hash": payload_hash,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def ingest_catalog(
    manifest: MerchantProviderManifest,
    observations: list[OfferObservation],
    *,
    now: int | None = None,
) -> dict[str, Any]:
    mismatched = [
        item.observation_id
        for item in observations
        if item.merchant_id != manifest.provider_id
    ]
    if mismatched:
        raise GOIARepositoryError("observation_merchant_mismatch")

    merchant = upsert_merchant(manifest, now=now)
    results = [ingest_observation(item, now=now) for item in observations]
    return {
        "status": "ok",
        "provider": merchant,
        "observations": {
            "submitted": len(results),
            "created": sum(item["state"] == "created" for item in results),
            "duplicates": sum(item["state"] == "duplicate" for item in results),
            "items": results,
        },
    }


def list_current_observations(
    *,
    kind: str,
    currency: str,
    now: int,
    limit: int = 500,
) -> list[dict[str, Any]]:
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT o.*, m.manifest_json
            FROM goia_offer_observations o
            JOIN goia_merchants m ON m.provider_id = o.merchant_id
            WHERE o.kind = {marker}
              AND o.currency = {marker}
              AND o.availability IN ('available', 'limited')
              AND o.sponsored = 0
              AND o.expires_at > {marker}
            ORDER BY o.observed_at DESC, o.observation_id ASC
            LIMIT {marker}
            """,
            (kind, currency, now, max(1, min(int(limit), 1_000))),
        )
        return [dict(item) for item in cur.fetchall()]
    finally:
        release_conn(conn)


def goia_index_stats(*, now: int | None = None) -> dict[str, Any]:
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) AS count FROM goia_merchants")
        merchants = int(_row(cur.fetchone())["count"])
        cur.execute("SELECT COUNT(*) AS count FROM goia_offer_observations")
        observations = int(_row(cur.fetchone())["count"])
        cur.execute(
            f"SELECT COUNT(*) AS count FROM goia_offer_observations WHERE expires_at > {marker}",
            (timestamp,),
        )
        current = int(_row(cur.fetchone())["count"])
        return {
            "status": "ok",
            "merchants": merchants,
            "observations": observations,
            "current_observations": current,
            "expired_observations": observations - current,
            "as_of": timestamp,
        }
    finally:
        release_conn(conn)


def enqueue_collection_job(
    *,
    provider_id: str,
    url: str,
    idempotency_key: str,
    job_type: str = "page",
    parent_job_id: str | None = None,
    priority: int = 50,
    now: int | None = None,
) -> dict[str, Any]:
    if job_type not in {"page", "sitemap", "catalog_json", "provider_manifest"}:
        raise GOIARepositoryError("invalid_collection_job_type")
    bounded_priority = max(0, min(int(priority), 100))
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT * FROM goia_collection_jobs WHERE idempotency_key = {marker}",
            (idempotency_key,),
        )
        existing = _row(cur.fetchone())
        if existing is not None:
            if (
                existing["url"] != url
                or existing["provider_id"] != provider_id
                or existing["job_type"] != job_type
                or existing["parent_job_id"] != parent_job_id
            ):
                raise GOIARepositoryError("collection_idempotency_conflict")
            return {
                "job_id": existing["job_id"],
                "state": "duplicate",
                "status": existing["status"],
            }
        cur.execute(
            f"SELECT provider_id FROM goia_merchants WHERE provider_id = {marker}",
            (provider_id,),
        )
        if cur.fetchone() is None:
            raise GOIARepositoryError("merchant_not_found")
        job_id = f"goj_{uuid.uuid4().hex}"
        cur.execute(
            f"""
            INSERT INTO goia_collection_jobs (
                job_id, idempotency_key, provider_id, url, job_type,
                parent_job_id, priority, status, attempts,
                created_at, updated_at
            ) VALUES ({", ".join([marker] * 11)})
            """,
            (
                job_id,
                idempotency_key,
                provider_id,
                url,
                job_type,
                parent_job_id,
                bounded_priority,
                "queued",
                0,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
        return {"job_id": job_id, "state": "created", "status": "queued"}
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def claim_collection_job(*, now: int | None = None) -> dict[str, Any] | None:
    timestamp = int(now or time.time())
    marker = qmark()
    for _attempt in range(3):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT * FROM goia_collection_jobs
                WHERE status = 'queued'
                ORDER BY priority DESC, created_at ASC, job_id ASC
                LIMIT 1
                """
            )
            selected = _row(cur.fetchone())
            if selected is None:
                return None
            cur.execute(
                f"""
                UPDATE goia_collection_jobs
                SET status = 'processing', attempts = attempts + 1,
                    started_at = {marker}, updated_at = {marker}
                WHERE job_id = {marker} AND status = 'queued'
                """,
                (timestamp, timestamp, selected["job_id"]),
            )
            if cur.rowcount != 1:
                conn.rollback()
                continue
            conn.commit()
            selected["status"] = "processing"
            selected["attempts"] = int(selected["attempts"]) + 1
            selected["started_at"] = timestamp
            return selected
        finally:
            release_conn(conn)
    return None


def complete_collection_job(
    job_id: str,
    *,
    result: dict[str, Any],
    now: int | None = None,
) -> None:
    _finish_collection_job(
        job_id,
        status="completed",
        result_json=_canonical_json(result),
        error_code=None,
        now=now,
    )


def fail_collection_job(
    job_id: str,
    *,
    error_code: str,
    now: int | None = None,
) -> None:
    _finish_collection_job(
        job_id,
        status="failed",
        result_json=None,
        error_code=str(error_code)[:160],
        now=now,
    )


def _finish_collection_job(
    job_id: str,
    *,
    status: str,
    result_json: str | None,
    error_code: str | None,
    now: int | None,
) -> None:
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE goia_collection_jobs
            SET status = {marker}, result_json = {marker}, error_code = {marker},
                completed_at = {marker}, updated_at = {marker}
            WHERE job_id = {marker} AND status = 'processing'
            """,
            (status, result_json, error_code, timestamp, timestamp, job_id),
        )
        if cur.rowcount != 1:
            raise GOIARepositoryError("collection_job_not_processing")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def collection_job_stats() -> dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM goia_collection_jobs
            GROUP BY status
            """
        )
        counts = {str(row["status"]): int(row["count"]) for row in map(dict, cur.fetchall())}
        cur.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM goia_review_candidates
            GROUP BY status
            """
        )
        candidate_counts = {
            str(row["status"]): int(row["count"])
            for row in map(dict, cur.fetchall())
        }
        return {
            "status": "ok",
            "jobs": {
                "queued": counts.get("queued", 0),
                "processing": counts.get("processing", 0),
                "completed": counts.get("completed", 0),
                "legacy_review_required": counts.get("review_required", 0),
                "failed": counts.get("failed", 0),
            },
            "candidates": {
                "pending_review": candidate_counts.get("pending_review", 0),
                "approved": candidate_counts.get("approved", 0),
                "quarantined": candidate_counts.get("quarantined", 0),
                "quarantine_exhausted": candidate_counts.get(
                    "quarantine_exhausted",
                    0,
                ),
                "rejected": candidate_counts.get("rejected", 0),
            },
            "collection_direct_publication": False,
            "autonomous_policy_publication": True,
            "autonomous_review": True,
            "autonomous_recovery": True,
        }
    finally:
        release_conn(conn)


def store_review_candidates(
    *,
    job_id: str,
    provider_id: str,
    candidates: list[dict[str, Any]],
    now: int | None = None,
) -> list[str]:
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    identifiers: list[str] = []
    try:
        for candidate in candidates[:500]:
            source_url = str(candidate.get("source_url") or "")
            source_sha256 = str(candidate.get("source_sha256") or "")
            if not source_url or len(source_sha256) != 64:
                raise GOIARepositoryError("candidate_source_evidence_required")
            raw_json = _canonical_json(candidate)
            raw_hash = _payload_hash(raw_json)
            candidate_id = f"goc_{hashlib.sha256(f'{job_id}:{raw_hash}'.encode()).hexdigest()[:32]}"
            cur.execute(
                f"""
                SELECT raw_hash FROM goia_review_candidates
                WHERE candidate_id = {marker}
                """,
                (candidate_id,),
            )
            existing = _row(cur.fetchone())
            if existing is None:
                cur.execute(
                    f"""
                    INSERT INTO goia_review_candidates (
                        candidate_id, job_id, provider_id, source_url,
                        source_sha256, raw_json, raw_hash, status,
                        created_at, updated_at
                    ) VALUES ({", ".join([marker] * 10)})
                    """,
                    (
                        candidate_id,
                        job_id,
                        provider_id,
                        source_url,
                        source_sha256,
                        raw_json,
                        raw_hash,
                        "pending_review",
                        timestamp,
                        timestamp,
                    ),
                )
            elif existing["raw_hash"] != raw_hash:
                raise GOIARepositoryError("candidate_identity_conflict")
            identifiers.append(candidate_id)
        conn.commit()
        return identifiers
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def list_review_candidates(
    *,
    status: str = "pending_review",
    limit: int = 100,
) -> dict[str, Any]:
    allowed = {
        "pending_review",
        "approved",
        "rejected",
        "quarantined",
        "quarantine_exhausted",
    }
    if status not in allowed:
        raise GOIARepositoryError("invalid_candidate_status")
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT * FROM goia_review_candidates
            WHERE status = {marker}
            ORDER BY created_at ASC, candidate_id ASC
            LIMIT {marker}
            """,
            (status, max(1, min(int(limit), 500))),
        )
        items = []
        for row in map(dict, cur.fetchall()):
            row["raw"] = json.loads(row.pop("raw_json"))
            normalized = row.pop("normalized_json", None)
            row["normalized"] = json.loads(normalized) if normalized else None
            row.pop("raw_hash", None)
            items.append(row)
        return {"status": "ok", "count": len(items), "items": items}
    finally:
        release_conn(conn)


def get_review_candidate(candidate_id: str) -> dict[str, Any]:
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT c.*, m.manifest_json
            FROM goia_review_candidates c
            JOIN goia_merchants m ON m.provider_id = c.provider_id
            WHERE c.candidate_id = {marker}
            """,
            (candidate_id,),
        )
        row = _row(cur.fetchone())
        if row is None:
            raise GOIARepositoryError("candidate_not_found")
        row["raw"] = json.loads(row.pop("raw_json"))
        row["provider_manifest"] = json.loads(row.pop("manifest_json"))
        normalized = row.pop("normalized_json", None)
        row["normalized"] = json.loads(normalized) if normalized else None
        row.pop("raw_hash", None)
        return row
    finally:
        release_conn(conn)


def quarantine_review_candidate(
    candidate_id: str,
    *,
    policy: str,
    reason: str,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT status, reviewer, reason FROM goia_review_candidates WHERE candidate_id = {marker}",
            (candidate_id,),
        )
        candidate = _row(cur.fetchone())
        if candidate is None:
            raise GOIARepositoryError("candidate_not_found")
        if candidate["status"] == "quarantined":
            if candidate["reviewer"] != policy or candidate["reason"] != reason:
                raise GOIARepositoryError("candidate_quarantine_conflict")
            return {
                "candidate_id": candidate_id,
                "state": "duplicate",
                "status": "quarantined",
                "reason": reason,
            }
        if candidate["status"] != "pending_review":
            raise GOIARepositoryError("candidate_not_pending")
        cur.execute(
            f"""
            UPDATE goia_review_candidates
            SET status = 'quarantined', reviewer = {marker}, reason = {marker},
                reviewed_at = {marker}, next_retry_at = {marker},
                updated_at = {marker}
            WHERE candidate_id = {marker} AND status = 'pending_review'
            """,
            (
                policy,
                reason,
                timestamp,
                timestamp + 3_600,
                timestamp,
                candidate_id,
            ),
        )
        conn.commit()
        return {
            "candidate_id": candidate_id,
            "state": "quarantined",
            "status": "quarantined",
            "reason": reason,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def schedule_due_quarantine_retries(
    *,
    now: int | None = None,
    limit: int = 20,
    maximum_retries: int = 3,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    bounded_limit = max(1, min(int(limit), 100))
    bounded_maximum = max(1, min(int(maximum_retries), 10))
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT c.candidate_id, c.provider_id, c.retry_count, j.url
            FROM goia_review_candidates c
            JOIN goia_collection_jobs j ON j.job_id = c.job_id
            WHERE c.status = 'quarantined'
              AND c.next_retry_at IS NOT NULL
              AND c.next_retry_at <= {marker}
            ORDER BY c.next_retry_at ASC, c.candidate_id ASC
            LIMIT {marker}
            """,
            (timestamp, bounded_limit),
        )
        due = [dict(item) for item in cur.fetchall()]
    finally:
        release_conn(conn)

    scheduled = []
    exhausted = []
    for candidate in due:
        retry_count = int(candidate["retry_count"])
        if retry_count >= bounded_maximum:
            conn = get_conn()
            cur = conn.cursor()
            try:
                cur.execute(
                    f"""
                    UPDATE goia_review_candidates
                    SET status = 'quarantine_exhausted', next_retry_at = NULL,
                        updated_at = {marker}
                    WHERE candidate_id = {marker} AND status = 'quarantined'
                    """,
                    (timestamp, candidate["candidate_id"]),
                )
                conn.commit()
                if cur.rowcount == 1:
                    exhausted.append(candidate["candidate_id"])
            finally:
                release_conn(conn)
            continue

        next_count = retry_count + 1
        retry = enqueue_collection_job(
            provider_id=candidate["provider_id"],
            url=candidate["url"],
            idempotency_key=f"goia-quarantine:{candidate['candidate_id']}:{next_count}",
            job_type="page",
            parent_job_id=candidate["last_retry_job_id"]
            if "last_retry_job_id" in candidate
            else None,
            priority=75,
            now=timestamp,
        )
        delay = min(86_400, 3_600 * (2**next_count))
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE goia_review_candidates
                SET retry_count = {marker}, next_retry_at = {marker},
                    last_retry_job_id = {marker}, updated_at = {marker}
                WHERE candidate_id = {marker} AND status = 'quarantined'
                  AND retry_count = {marker}
                """,
                (
                    next_count,
                    timestamp + delay,
                    retry["job_id"],
                    timestamp,
                    candidate["candidate_id"],
                    retry_count,
                ),
            )
            conn.commit()
            if cur.rowcount == 1:
                scheduled.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "job_id": retry["job_id"],
                        "retry_count": next_count,
                        "next_retry_at": timestamp + delay,
                    }
                )
        finally:
            release_conn(conn)
    return {
        "status": "ok",
        "scheduled_count": len(scheduled),
        "exhausted_count": len(exhausted),
        "scheduled": scheduled,
        "exhausted": exhausted,
    }


def recover_stale_collection_jobs(
    *,
    now: int | None = None,
    lease_seconds: int = 300,
    maximum_attempts: int = 3,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    lease = max(60, min(int(lease_seconds), 3_600))
    maximum = max(1, min(int(maximum_attempts), 10))
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE goia_collection_jobs
            SET status = 'queued', started_at = NULL,
                error_code = 'stale_lease_recovered', updated_at = {marker}
            WHERE status = 'processing'
              AND started_at IS NOT NULL
              AND started_at <= {marker}
              AND attempts < {marker}
            """,
            (timestamp, timestamp - lease, maximum),
        )
        recovered = cur.rowcount
        cur.execute(
            f"""
            UPDATE goia_collection_jobs
            SET status = 'failed', completed_at = {marker},
                error_code = 'stale_lease_attempts_exhausted',
                updated_at = {marker}
            WHERE status = 'processing'
              AND started_at IS NOT NULL
              AND started_at <= {marker}
              AND attempts >= {marker}
            """,
            (timestamp, timestamp, timestamp - lease, maximum),
        )
        exhausted = cur.rowcount
        conn.commit()
        return {
            "status": "ok",
            "recovered_count": recovered,
            "exhausted_count": exhausted,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def record_anonymous_demand(
    *,
    query_fingerprint: str,
    kind: str,
    country: str,
    currency: str,
    result_count: int,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    period_day = timestamp // 86_400
    satisfied = int(result_count > 0)
    unmet = int(result_count == 0)
    signal_key = hashlib.sha256(
        f"{period_day}:{query_fingerprint}:{kind}:{country}:{currency}".encode()
    ).hexdigest()
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            INSERT INTO goia_demand_signals (
                signal_key, period_day, query_fingerprint, kind, country,
                currency, request_count, satisfied_count, unmet_count,
                matched_result_count, created_at, updated_at
            ) VALUES ({", ".join([marker] * 12)})
            ON CONFLICT(signal_key) DO UPDATE SET
                request_count = goia_demand_signals.request_count + 1,
                satisfied_count = goia_demand_signals.satisfied_count + {marker},
                unmet_count = goia_demand_signals.unmet_count + {marker},
                matched_result_count = goia_demand_signals.matched_result_count + {marker},
                updated_at = {marker}
            """,
            (
                signal_key,
                period_day,
                query_fingerprint,
                kind,
                country,
                currency,
                1,
                satisfied,
                unmet,
                max(0, int(result_count)),
                timestamp,
                timestamp,
                satisfied,
                unmet,
                max(0, int(result_count)),
                timestamp,
            ),
        )
        conn.commit()
        return {
            "signal_key": signal_key,
            "period_day": period_day,
            "aggregated": True,
            "raw_query_stored": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def demand_signal_stats(*, days: int = 30, now: int | None = None) -> dict[str, Any]:
    timestamp = int(now or time.time())
    minimum_day = timestamp // 86_400 - max(1, min(int(days), 365)) + 1
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT kind, country, currency,
                   SUM(request_count) AS demand_count,
                   SUM(satisfied_count) AS satisfied_count,
                   SUM(unmet_count) AS unmet_count,
                   SUM(matched_result_count) AS matched_result_count
            FROM goia_demand_signals
            WHERE period_day >= {marker}
            GROUP BY kind, country, currency
            ORDER BY unmet_count DESC, demand_count DESC, kind ASC
            """,
            (minimum_day,),
        )
        markets = [dict(item) for item in cur.fetchall()]
        return {
            "status": "ok",
            "days": max(1, min(int(days), 365)),
            "markets": markets,
            "privacy": {
                "buyer_identity_stored": False,
                "raw_query_stored": False,
                "query_fingerprint_only": True,
            },
        }
    finally:
        release_conn(conn)


def refresh_partnership_opportunities(
    *,
    days: int = 30,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    demand = demand_signal_stats(days=days, now=timestamp)["markets"]
    conn = get_conn()
    cur = conn.cursor()
    try:
        marker = qmark()
        cur.execute(
            f"""
            SELECT o.kind, o.currency, o.merchant_id, o.offer_id, m.manifest_json
            FROM goia_offer_observations o
            JOIN goia_merchants m ON m.provider_id = o.merchant_id
            WHERE o.expires_at > {marker}
              AND o.availability IN ('available', 'limited')
              AND o.sponsored = 0
            """,
            (timestamp,),
        )
        offer_rows = [dict(item) for item in cur.fetchall()]
    finally:
        release_conn(conn)

    coverage: dict[tuple[str, str, str], set[tuple[str, str]]] = {}
    for row in offer_rows:
        manifest = json.loads(row["manifest_json"])
        for country in manifest.get("countries") or []:
            key = (row["kind"], country, row["currency"])
            coverage.setdefault(key, set()).add((row["merchant_id"], row["offer_id"]))

    refreshed = []
    marker = qmark()
    for market in demand:
        key = (market["kind"], market["country"], market["currency"])
        offer_count = len(coverage.get(key, set()))
        demand_count = int(market["demand_count"])
        unmet_count = int(market["unmet_count"])
        unmet_ratio = unmet_count / max(1, demand_count)
        scarcity = max(0, 10 - offer_count)
        gap_score = min(
            100,
            round(unmet_ratio * 60 + min(demand_count, 20) + scarcity * 2),
        )
        status = "qualified" if gap_score >= 60 else "monitoring"
        reason = (
            "high_unmet_demand_and_low_offer_coverage"
            if status == "qualified"
            else "insufficient_gap_evidence"
        )
        opportunity_id = "gpo_" + hashlib.sha256(":".join(key).encode()).hexdigest()[:32]
        evidence = {
            "window_days": max(1, min(int(days), 365)),
            "demand_count": demand_count,
            "unmet_count": unmet_count,
            "unmet_ratio": round(unmet_ratio, 6),
            "current_offer_count": offer_count,
            "raw_queries_included": False,
            "buyer_identity_included": False,
        }
        evidence_json = _canonical_json(evidence)
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                INSERT INTO goia_partnership_opportunities (
                    opportunity_id, kind, country, currency, demand_count,
                    unmet_count, current_offer_count, gap_score, status,
                    reason, evidence_json, created_at, updated_at
                ) VALUES ({", ".join([marker] * 13)})
                ON CONFLICT(opportunity_id) DO UPDATE SET
                    demand_count = {marker}, unmet_count = {marker},
                    current_offer_count = {marker}, gap_score = {marker},
                    status = {marker}, reason = {marker},
                    evidence_json = {marker}, updated_at = {marker}
                """,
                (
                    opportunity_id,
                    *key,
                    demand_count,
                    unmet_count,
                    offer_count,
                    gap_score,
                    status,
                    reason,
                    evidence_json,
                    timestamp,
                    timestamp,
                    demand_count,
                    unmet_count,
                    offer_count,
                    gap_score,
                    status,
                    reason,
                    evidence_json,
                    timestamp,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            release_conn(conn)
        refreshed.append(
            {
                "opportunity_id": opportunity_id,
                "status": status,
                "gap_score": gap_score,
            }
        )
    return {
        "status": "ok",
        "refreshed_count": len(refreshed),
        "qualified_count": sum(item["status"] == "qualified" for item in refreshed),
        "items": refreshed,
        "outreach_triggered": False,
    }


def list_partnership_opportunities(
    *,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if status is not None and status not in {"monitoring", "qualified"}:
        raise GOIARepositoryError("invalid_opportunity_status")
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        if status is None:
            cur.execute(
                f"""
                SELECT * FROM goia_partnership_opportunities
                ORDER BY gap_score DESC, opportunity_id ASC
                LIMIT {marker}
                """,
                (max(1, min(int(limit), 500)),),
            )
        else:
            cur.execute(
                f"""
                SELECT * FROM goia_partnership_opportunities
                WHERE status = {marker}
                ORDER BY gap_score DESC, opportunity_id ASC
                LIMIT {marker}
                """,
                (status, max(1, min(int(limit), 500))),
            )
        items = []
        for row in map(dict, cur.fetchall()):
            row["evidence"] = json.loads(row.pop("evidence_json"))
            items.append(row)
        return {
            "status": "ok",
            "count": len(items),
            "items": items,
            "outreach_triggered": False,
        }
    finally:
        release_conn(conn)


def upsert_partner_hints(
    hints: list[dict[str, Any]],
    *,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    marker = qmark()
    stored = []
    for hint in hints[:500]:
        domain = str(hint.get("domain") or "").strip().lower().rstrip(".")
        if not domain or len(domain) > 253:
            continue
        evidence = {
            "source_url": str(hint.get("source_url") or "")[:2_000],
            "source_sha256": str(hint.get("source_sha256") or "")[:64],
            "evidence_type": str(hint.get("evidence_type") or "")[:80],
            "url": str(hint.get("url") or "")[:2_000],
        }
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                f"SELECT * FROM goia_partner_prospects WHERE domain = {marker}",
                (domain,),
            )
            existing = _row(cur.fetchone())
            evidence_items = json.loads(existing["evidence_json"]) if existing else []
            if evidence not in evidence_items:
                evidence_items.append(evidence)
            evidence_items = evidence_items[-50:]
            signals = json.loads(existing["signals_json"]) if existing else {
                "kinds": [],
                "currencies": [],
            }
            signals["kinds"] = sorted(
                set(signals.get("kinds") or []) | set(hint.get("kinds") or [])
            )[:20]
            signals["currencies"] = sorted(
                set(signals.get("currencies") or []) | set(hint.get("currencies") or [])
            )[:20]
            seller_evidence = sum(
                item["evidence_type"] == "schema_offer_seller" for item in evidence_items
            )
            relevance_score = min(100, 25 + len(evidence_items) * 10 + seller_evidence * 15)
            status = "qualified" if relevance_score >= 60 else "discovered"
            prospect_id = "gpp_" + hashlib.sha256(domain.encode()).hexdigest()[:32]
            values = (
                prospect_id,
                domain,
                str(hint.get("name") or (existing or {}).get("name") or domain)[:300],
                status,
                relevance_score,
                len(evidence_items),
                _canonical_json(signals),
                _canonical_json(evidence_items),
                0,
                0,
                existing["created_at"] if existing else timestamp,
                timestamp,
            )
            cur.execute(
                f"""
                INSERT INTO goia_partner_prospects (
                    prospect_id, domain, name, status, relevance_score,
                    evidence_count, signals_json, evidence_json,
                    outreach_authorized, contact_attempted, created_at, updated_at
                ) VALUES ({", ".join([marker] * 12)})
                ON CONFLICT(domain) DO UPDATE SET
                    name = {marker}, status = {marker}, relevance_score = {marker},
                    evidence_count = {marker}, signals_json = {marker},
                    evidence_json = {marker}, updated_at = {marker}
                """,
                values
                + (
                    values[2],
                    status,
                    relevance_score,
                    len(evidence_items),
                    values[6],
                    values[7],
                    timestamp,
                ),
            )
            conn.commit()
            stored.append(prospect_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            release_conn(conn)
    return {
        "status": "ok",
        "stored_count": len(set(stored)),
        "prospect_ids": sorted(set(stored)),
        "network_access_performed": False,
        "outreach_triggered": False,
    }


def refresh_opportunity_prospect_links(*, now: int | None = None) -> dict[str, Any]:
    timestamp = int(now or time.time())
    conn = get_conn()
    cur = conn.cursor()
    marker = qmark()
    linked = 0
    try:
        cur.execute(
            """
            SELECT opportunity_id, kind, currency
            FROM goia_partnership_opportunities
            WHERE status = 'qualified'
            """
        )
        opportunities = list(map(dict, cur.fetchall()))
        cur.execute(
            """
            SELECT prospect_id, relevance_score, signals_json
            FROM goia_partner_prospects
            WHERE status = 'qualified'
            """
        )
        prospects = list(map(dict, cur.fetchall()))
        for opportunity in opportunities:
            for prospect in prospects:
                signals = json.loads(prospect["signals_json"])
                schema_kind = {
                    "software": "SoftwareApplication",
                    "api": "SoftwareApplication",
                    "hosting": "Service",
                    "digital_service": "Service",
                }.get(opportunity["kind"])
                kind_match = schema_kind in (signals.get("kinds") or [])
                currency_match = opportunity["currency"] in (signals.get("currencies") or [])
                if not kind_match or not currency_match:
                    continue
                score = min(100, int(prospect["relevance_score"]) + 20)
                cur.execute(
                    f"""
                    INSERT INTO goia_opportunity_prospects (
                        opportunity_id, prospect_id, match_score, reason,
                        created_at, updated_at
                    ) VALUES ({", ".join([marker] * 6)})
                    ON CONFLICT(opportunity_id, prospect_id) DO UPDATE SET
                        match_score = {marker}, reason = {marker}, updated_at = {marker}
                    """,
                    (
                        opportunity["opportunity_id"],
                        prospect["prospect_id"],
                        score,
                        "structured_kind_and_currency_match",
                        timestamp,
                        timestamp,
                        score,
                        "structured_kind_and_currency_match",
                        timestamp,
                    ),
                )
                linked += 1
        conn.commit()
        return {"status": "ok", "linked_count": linked, "outreach_triggered": False}
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def refresh_partner_permissions(*, now: int | None = None) -> dict[str, Any]:
    """Reconcile prospects with explicit provider opt-ins; never authorize outreach."""
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    matched = []
    try:
        cur.execute(
            f"""
            UPDATE goia_partner_prospects
            SET permission_status = 'none',
                permission_provider_id = NULL,
                permission_evidence_json = NULL,
                outreach_authorized = 0,
                updated_at = {marker}
            """,
            (timestamp,),
        )
        cur.execute(
            """
            SELECT m.provider_id, m.website, m.manifest_json, m.manifest_hash,
                   v.manifest_hash AS verified_manifest_hash,
                   v.source_url AS verification_source_url,
                   v.source_sha256 AS verification_source_sha256,
                   v.verified_at, v.expires_at AS verification_expires_at
            FROM goia_merchants m
            LEFT JOIN goia_provider_verifications v
              ON v.provider_id = m.provider_id
            """
        )
        providers = list(map(dict, cur.fetchall()))
        cur.execute("SELECT * FROM goia_partnership_suppressions")
        suppressions = {
            row["domain"]: dict(row)
            for row in cur.fetchall()
        }
        cur.execute("SELECT prospect_id, domain FROM goia_partner_prospects")
        prospects = list(map(dict, cur.fetchall()))
        by_domain = {
            str(urlparse(row["website"]).hostname or "").lower().rstrip("."): row
            for row in providers
        }
        for prospect in prospects:
            suppression = suppressions.get(prospect["domain"])
            if suppression is not None:
                cur.execute(
                    f"""
                    UPDATE goia_partner_prospects
                    SET permission_status = 'suppressed',
                        permission_provider_id = {marker},
                        permission_evidence_json = {marker},
                        outreach_authorized = 0,
                        updated_at = {marker}
                    WHERE prospect_id = {marker}
                    """,
                    (
                        suppression.get("provider_id"),
                        _canonical_json(
                            {
                                "reason_code": suppression["reason_code"],
                                "source": suppression["source"],
                                "proposal_id": suppression.get("proposal_id"),
                            }
                        ),
                        timestamp,
                        prospect["prospect_id"],
                    ),
                )
                matched.append(
                    {
                        "prospect_id": prospect["prospect_id"],
                        "permission_status": "suppressed",
                    }
                )
                continue
            provider = by_domain.get(prospect["domain"])
            if provider is None:
                continue
            manifest = json.loads(provider["manifest_json"])
            policy = manifest.get("partnership_discovery") or {}
            if not policy.get("accepts_partnership_requests"):
                continue
            verification_current = (
                provider.get("verified_manifest_hash") == provider["manifest_hash"]
                and int(provider.get("verification_expires_at") or 0) > timestamp
                and provider.get("verification_source_url") == policy.get("manifest_url")
            )
            evidence = {
                "provider_id": provider["provider_id"],
                "manifest_hash": provider["manifest_hash"],
                "request_endpoint": policy.get("request_endpoint"),
                "terms_url": policy.get("terms_url"),
                "relationship_types": policy.get("relationship_types") or [],
                "domain_match": True,
                "self_hosting_verified": verification_current,
                "verification_source_sha256": (
                    provider.get("verification_source_sha256")
                    if verification_current
                    else None
                ),
                "verified_at": provider.get("verified_at") if verification_current else None,
                "verification_expires_at": (
                    provider.get("verification_expires_at")
                    if verification_current
                    else None
                ),
            }
            permission_status = (
                "verified_opt_in" if verification_current else "declared_opt_in"
            )
            cur.execute(
                f"""
                UPDATE goia_partner_prospects
                SET permission_status = {marker},
                    permission_provider_id = {marker},
                    permission_evidence_json = {marker},
                    outreach_authorized = {marker},
                    updated_at = {marker}
                WHERE prospect_id = {marker}
                """,
                (
                    permission_status,
                    provider["provider_id"],
                    _canonical_json(evidence),
                    int(verification_current),
                    timestamp,
                    prospect["prospect_id"],
                ),
            )
            matched.append(
                {
                    "prospect_id": prospect["prospect_id"],
                    "permission_status": permission_status,
                }
            )
        conn.commit()
        return {
            "status": "ok",
            "declared_opt_in_count": sum(
                item["permission_status"] == "declared_opt_in" for item in matched
            ),
            "verified_opt_in_count": sum(
                item["permission_status"] == "verified_opt_in" for item in matched
            ),
            "suppressed_count": sum(
                item["permission_status"] == "suppressed" for item in matched
            ),
            "prospect_ids": sorted(item["prospect_id"] for item in matched),
            "outreach_triggered": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def list_partner_prospects(
    *,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if status is not None and status not in {"discovered", "qualified"}:
        raise GOIARepositoryError("invalid_prospect_status")
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        query = "SELECT * FROM goia_partner_prospects"
        params: tuple[Any, ...]
        if status:
            query += f" WHERE status = {marker}"
            params = (status, max(1, min(int(limit), 500)))
        else:
            params = (max(1, min(int(limit), 500)),)
        query += f" ORDER BY relevance_score DESC, prospect_id ASC LIMIT {marker}"
        cur.execute(query, params)
        items = []
        for row in map(dict, cur.fetchall()):
            row["signals"] = json.loads(row.pop("signals_json"))
            row["evidence"] = json.loads(row.pop("evidence_json"))
            raw_permission = row.pop("permission_evidence_json")
            row["permission_evidence"] = (
                json.loads(raw_permission) if raw_permission else None
            )
            row["outreach_authorized"] = bool(row["outreach_authorized"])
            row["contact_attempted"] = bool(row["contact_attempted"])
            items.append(row)
        return {
            "status": "ok",
            "count": len(items),
            "items": items,
            "network_access_performed": False,
            "outreach_triggered": False,
        }
    finally:
        release_conn(conn)


def seed_due_catalog_sources(
    *,
    now: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT provider_id, manifest_json
            FROM goia_merchants
            ORDER BY provider_id ASC
            """
        )
        merchants = [dict(item) for item in cur.fetchall()]
    finally:
        release_conn(conn)

    seeded = []
    unsupported = []
    for merchant in merchants:
        manifest = json.loads(merchant["manifest_json"])
        policy = manifest.get("partnership_discovery") or {}
        if policy.get("accepts_partnership_requests") and len(seeded) < max(
            1, min(int(limit), 500)
        ):
            interval = max(
                3_600,
                min(int(policy.get("verification_interval_seconds") or 86_400), 604_800),
            )
            window = timestamp // interval
            result = enqueue_collection_job(
                provider_id=merchant["provider_id"],
                url=str(policy["manifest_url"]),
                idempotency_key=f"goia-provider-manifest:{merchant['provider_id']}:{window}",
                job_type="provider_manifest",
                priority=95,
                now=timestamp,
            )
            if result["state"] == "created":
                seeded.append(
                    {
                        "provider_id": merchant["provider_id"],
                        "source_id": "partnership_manifest",
                        "job_id": result["job_id"],
                    }
                )
        for source in manifest.get("catalogs") or []:
            if len(seeded) >= max(1, min(int(limit), 500)):
                break
            source_type = str(source.get("source_type") or "")
            if source_type not in {"sitemap", "goia_json"}:
                unsupported.append(
                    {
                        "provider_id": merchant["provider_id"],
                        "source_id": source.get("source_id"),
                        "source_type": source_type,
                    }
                )
                continue
            interval = max(300, min(int(source["refresh_interval_seconds"]), 2_592_000))
            window = timestamp // interval
            result = enqueue_collection_job(
                provider_id=merchant["provider_id"],
                url=str(source["url"]),
                idempotency_key=(
                    f"goia-source:{merchant['provider_id']}:{source['source_id']}:{window}"
                ),
                job_type="sitemap" if source_type == "sitemap" else "catalog_json",
                priority=100 if source_type == "sitemap" else 90,
                now=timestamp,
            )
            if result["state"] == "created":
                seeded.append(
                    {
                        "provider_id": merchant["provider_id"],
                        "source_id": source["source_id"],
                        "job_id": result["job_id"],
                    }
                )
    return {
        "status": "ok",
        "seeded_count": len(seeded),
        "unsupported_count": len(unsupported),
        "seeded": seeded,
        "unsupported": unsupported,
    }


def record_provider_manifest_verification(
    *,
    provider_id: str,
    manifest: MerchantProviderManifest,
    source_url: str,
    source_sha256: str,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    payload_json = _canonical_json(manifest.model_dump(mode="json"))
    manifest_hash = _payload_hash(payload_json)
    policy = manifest.partnership_discovery
    if not policy.accepts_partnership_requests:
        raise GOIARepositoryError("provider_manifest_partnership_opt_in_required")
    if str(policy.manifest_url) != source_url:
        raise GOIARepositoryError("provider_manifest_source_mismatch")
    if (
        len(source_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_sha256)
    ):
        raise GOIARepositoryError("invalid_provider_manifest_source_hash")
    expires_at = timestamp + min(
        int(policy.verification_interval_seconds) * 2,
        604_800,
    )
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT manifest_hash FROM goia_merchants
            WHERE provider_id = {marker}
            """,
            (provider_id,),
        )
        merchant = _row(cur.fetchone())
        if merchant is None:
            raise GOIARepositoryError("merchant_not_found")
        if merchant["manifest_hash"] != manifest_hash:
            raise GOIARepositoryError("provider_manifest_hash_mismatch")
        cur.execute(
            f"""
            INSERT INTO goia_provider_verifications (
                provider_id, manifest_hash, source_url, source_sha256,
                verified_at, expires_at, updated_at
            ) VALUES ({", ".join([marker] * 7)})
            ON CONFLICT(provider_id) DO UPDATE SET
                manifest_hash = {marker}, source_url = {marker},
                source_sha256 = {marker}, verified_at = {marker},
                expires_at = {marker}, updated_at = {marker}
            """,
            (
                provider_id,
                manifest_hash,
                source_url,
                source_sha256,
                timestamp,
                expires_at,
                timestamp,
                manifest_hash,
                source_url,
                source_sha256,
                timestamp,
                expires_at,
                timestamp,
            ),
        )
        conn.commit()
        return {
            "status": "verified",
            "provider_id": provider_id,
            "manifest_hash": manifest_hash,
            "verified_at": timestamp,
            "expires_at": expires_at,
            "outreach_triggered": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def list_provider_verifications(
    *,
    limit: int = 100,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT v.*, m.manifest_hash AS current_manifest_hash
            FROM goia_provider_verifications v
            JOIN goia_merchants m ON m.provider_id = v.provider_id
            ORDER BY v.verified_at DESC, v.provider_id ASC
            LIMIT {marker}
            """,
            (max(1, min(int(limit), 500)),),
        )
        items = []
        for row in map(dict, cur.fetchall()):
            row["current"] = (
                row["manifest_hash"] == row.pop("current_manifest_hash")
                and row["expires_at"] > timestamp
            )
            items.append(row)
        return {
            "status": "ok",
            "count": len(items),
            "items": items,
            "as_of": timestamp,
            "outreach_triggered": False,
        }
    finally:
        release_conn(conn)


def prepare_partner_proposals(*, now: int | None = None, limit: int = 100) -> dict[str, Any]:
    timestamp = int(now or time.time())
    bounded_limit = max(1, min(int(limit), 500))
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    prepared = []
    duplicates = 0
    try:
        cur.execute(
            f"""
            UPDATE goia_partnership_outbox
            SET status = 'expired', updated_at = {marker}
            WHERE status IN ('prepared', 'retryable') AND expires_at <= {marker}
            """,
            (timestamp, timestamp),
        )
        cur.execute(
            f"""
            UPDATE goia_partnership_outbox
            SET status = 'cancelled', updated_at = {marker}
            WHERE status IN ('prepared', 'retryable')
              AND NOT EXISTS (
                  SELECT 1
                  FROM goia_partner_prospects p
                  JOIN goia_provider_verifications v
                    ON v.provider_id = p.permission_provider_id
                  WHERE p.prospect_id = goia_partnership_outbox.prospect_id
                    AND p.permission_status = 'verified_opt_in'
                    AND p.outreach_authorized = 1
                    AND v.manifest_hash = goia_partnership_outbox.manifest_hash
                    AND v.expires_at > {marker}
              )
            """,
            (timestamp, timestamp),
        )
        cur.execute(
            f"""
            SELECT l.opportunity_id, l.prospect_id, p.permission_provider_id AS provider_id,
                   p.permission_evidence_json, p.outreach_authorized,
                   o.kind, o.country, o.currency, o.demand_count, o.unmet_count,
                   o.current_offer_count, o.gap_score, m.manifest_hash,
                   v.expires_at AS verification_expires_at
            FROM goia_opportunity_prospects l
            JOIN goia_partnership_opportunities o
              ON o.opportunity_id = l.opportunity_id
            JOIN goia_partner_prospects p ON p.prospect_id = l.prospect_id
            JOIN goia_merchants m ON m.provider_id = p.permission_provider_id
            JOIN goia_provider_verifications v ON v.provider_id = m.provider_id
            WHERE o.status = 'qualified'
              AND p.permission_status = 'verified_opt_in'
              AND p.outreach_authorized = 1
              AND v.manifest_hash = m.manifest_hash
              AND v.expires_at > {marker}
            ORDER BY o.gap_score DESC, l.match_score DESC, l.opportunity_id ASC
            LIMIT {marker}
            """,
            (timestamp, bounded_limit),
        )
        rows = list(map(dict, cur.fetchall()))
        for row in rows:
            permission = json.loads(row["permission_evidence_json"])
            relationship_types = sorted(permission.get("relationship_types") or [])
            if not relationship_types:
                continue
            identity = ":".join(
                (row["opportunity_id"], row["prospect_id"], row["manifest_hash"])
            )
            proposal_id = "gpr_" + hashlib.sha256(identity.encode()).hexdigest()[:32]
            expires_at = min(
                timestamp + 86_400,
                int(row["verification_expires_at"]),
            )
            proposal = PartnershipProposal(
                proposal_id=proposal_id,
                opportunity_id=row["opportunity_id"],
                prospect_id=row["prospect_id"],
                provider_id=row["provider_id"],
                request_endpoint=permission["request_endpoint"],
                relationship_type=relationship_types[0],
                market={
                    "kind": row["kind"],
                    "country": row["country"],
                    "currency": row["currency"],
                },
                aggregate_evidence={
                    "demand_count": int(row["demand_count"]),
                    "unmet_count": int(row["unmet_count"]),
                    "current_offer_count": int(row["current_offer_count"]),
                    "gap_score": int(row["gap_score"]),
                },
                created_at=timestamp,
                expires_at=expires_at,
            )
            payload_json = _canonical_json(proposal.model_dump(mode="json"))
            payload_hash = _payload_hash(payload_json)
            cur.execute(
                f"SELECT proposal_id FROM goia_partnership_outbox WHERE proposal_id = {marker}",
                (proposal_id,),
            )
            if cur.fetchone() is not None:
                duplicates += 1
                continue
            cur.execute(
                f"""
                INSERT INTO goia_partnership_outbox (
                    proposal_id, opportunity_id, prospect_id, provider_id,
                    endpoint, status, payload_json, payload_hash, manifest_hash,
                    next_attempt_at, created_at, expires_at, updated_at
                ) VALUES ({", ".join([marker] * 13)})
                """,
                (
                    proposal_id,
                    row["opportunity_id"],
                    row["prospect_id"],
                    row["provider_id"],
                    permission["request_endpoint"],
                    "prepared",
                    payload_json,
                    payload_hash,
                    row["manifest_hash"],
                    timestamp,
                    timestamp,
                    expires_at,
                    timestamp,
                ),
            )
            prepared.append(proposal_id)
        conn.commit()
        return {
            "status": "ok",
            "prepared_count": len(prepared),
            "duplicate_count": duplicates,
            "proposal_ids": prepared,
            "delivery_enabled": False,
            "network_access_performed": False,
            "outreach_triggered": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def claim_partner_proposal(
    *,
    now: int | None = None,
    lease_seconds: int = 120,
) -> dict[str, Any] | None:
    timestamp = int(now or time.time())
    lease_until = timestamp + max(30, min(int(lease_seconds), 600))
    marker = qmark()
    for _attempt in range(3):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                SELECT o.*
                FROM goia_partnership_outbox o
                JOIN goia_partner_prospects p ON p.prospect_id = o.prospect_id
                JOIN goia_merchants m ON m.provider_id = o.provider_id
                JOIN goia_provider_verifications v ON v.provider_id = o.provider_id
                WHERE o.status IN ('prepared', 'retryable')
                  AND o.next_attempt_at <= {marker}
                  AND o.expires_at > {marker}
                  AND p.permission_status = 'verified_opt_in'
                  AND p.outreach_authorized = 1
                  AND m.manifest_hash = o.manifest_hash
                  AND v.manifest_hash = o.manifest_hash
                  AND v.expires_at > {marker}
                  AND NOT EXISTS (
                      SELECT 1 FROM goia_partnership_outbox active
                      WHERE active.prospect_id = o.prospect_id
                        AND active.status = 'delivering'
                  )
                ORDER BY o.created_at ASC, o.proposal_id ASC
                LIMIT 1
                """,
                (timestamp, timestamp, timestamp),
            )
            selected = _row(cur.fetchone())
            if selected is None:
                return None
            lease_token = uuid.uuid4().hex
            cur.execute(
                f"""
                UPDATE goia_partnership_outbox
                SET status = 'delivering', attempts = attempts + 1,
                    lease_token = {marker}, lease_until = {marker},
                    updated_at = {marker}
                WHERE proposal_id = {marker}
                  AND status IN ('prepared', 'retryable')
                """,
                (lease_token, lease_until, timestamp, selected["proposal_id"]),
            )
            if cur.rowcount != 1:
                conn.rollback()
                continue
            _insert_partner_delivery_event(
                cur,
                proposal_id=selected["proposal_id"],
                event_type="delivery_claimed",
                from_status=selected["status"],
                to_status="delivering",
                reason=None,
                now=timestamp,
            )
            conn.commit()
            selected["status"] = "delivering"
            selected["attempts"] = int(selected["attempts"]) + 1
            selected["lease_token"] = lease_token
            selected["lease_until"] = lease_until
            selected["payload"] = json.loads(selected.pop("payload_json"))
            return selected
        finally:
            release_conn(conn)
    return None


def finish_partner_proposal_delivery(
    proposal_id: str,
    *,
    lease_token: str,
    delivered: bool,
    retryable: bool = False,
    error_code: str | None = None,
    receipt: dict[str, Any] | None = None,
    now: int | None = None,
    maximum_attempts: int = 3,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    if delivered:
        try:
            acknowledgement = PartnershipAcknowledgement.model_validate(receipt)
        except Exception as exc:
            raise GOIARepositoryError("valid_delivery_receipt_required") from exc
        if acknowledgement.proposal_id != proposal_id:
            raise GOIARepositoryError("delivery_receipt_proposal_mismatch")
        receipt = acknowledgement.model_dump(mode="json")
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT status, attempts, prospect_id
            FROM goia_partnership_outbox
            WHERE proposal_id = {marker} AND lease_token = {marker}
            """,
            (proposal_id, lease_token),
        )
        current = _row(cur.fetchone())
        if current is None or current["status"] != "delivering":
            raise GOIARepositoryError("proposal_delivery_lease_invalid")
        if delivered:
            status = "delivered"
            next_attempt_at = timestamp
        elif retryable and int(current["attempts"]) < max(1, min(maximum_attempts, 10)):
            status = "retryable"
            next_attempt_at = timestamp + min(86_400, 60 * (2 ** int(current["attempts"])))
        else:
            status = "failed"
            next_attempt_at = timestamp
        cur.execute(
            f"""
            UPDATE goia_partnership_outbox
            SET status = {marker}, next_attempt_at = {marker},
                lease_token = NULL, lease_until = NULL,
                last_error_code = {marker}, receipt_json = {marker},
                delivered_at = {marker},
                updated_at = {marker}
            WHERE proposal_id = {marker} AND lease_token = {marker}
            """,
            (
                status,
                next_attempt_at,
                None if delivered else str(error_code or "delivery_failed")[:160],
                _canonical_json(receipt) if delivered and receipt else None,
                timestamp if delivered else None,
                timestamp,
                proposal_id,
                lease_token,
            ),
        )
        if delivered:
            cur.execute(
                f"""
                UPDATE goia_partner_prospects
                SET contact_attempted = 1, updated_at = {marker}
                WHERE prospect_id = {marker}
                """,
                (timestamp, current["prospect_id"]),
            )
            reason_code = str((receipt or {}).get("reason_code") or "")
            receipt_status = str((receipt or {}).get("status") or "")
            if receipt_status == "rejected" and reason_code in {
                "opt_out",
                "do_not_contact",
            }:
                cur.execute(
                    f"""
                    SELECT domain, permission_provider_id
                    FROM goia_partner_prospects
                    WHERE prospect_id = {marker}
                    """,
                    (current["prospect_id"],),
                )
                prospect = _row(cur.fetchone())
                cur.execute(
                    f"""
                    INSERT INTO goia_partnership_suppressions (
                        domain, provider_id, proposal_id, reason_code,
                        source, created_at, updated_at
                    ) VALUES ({", ".join([marker] * 7)})
                    ON CONFLICT(domain) DO UPDATE SET
                        provider_id = {marker}, proposal_id = {marker},
                        reason_code = {marker}, source = {marker},
                        updated_at = {marker}
                    """,
                    (
                        prospect["domain"],
                        prospect["permission_provider_id"],
                        proposal_id,
                        reason_code,
                        "merchant_acknowledgement",
                        timestamp,
                        timestamp,
                        prospect["permission_provider_id"],
                        proposal_id,
                        reason_code,
                        "merchant_acknowledgement",
                        timestamp,
                    ),
                )
                cur.execute(
                    f"""
                    UPDATE goia_partner_prospects
                    SET permission_status = 'suppressed',
                        outreach_authorized = 0, updated_at = {marker}
                    WHERE prospect_id = {marker}
                    """,
                    (timestamp, current["prospect_id"]),
                )
                cur.execute(
                    f"""
                    UPDATE goia_partnership_outbox
                    SET status = 'cancelled', updated_at = {marker},
                        last_error_code = 'merchant_opt_out'
                    WHERE prospect_id = {marker}
                      AND proposal_id <> {marker}
                      AND status IN ('prepared', 'retryable')
                    """,
                    (timestamp, current["prospect_id"], proposal_id),
                )
        _insert_partner_delivery_event(
            cur,
            proposal_id=proposal_id,
            event_type="delivery_completed" if delivered else "delivery_failed",
            from_status="delivering",
            to_status=status,
            reason=None if delivered else str(error_code or "delivery_failed")[:160],
            now=timestamp,
        )
        conn.commit()
        return {
            "proposal_id": proposal_id,
            "status": status,
            "attempts": int(current["attempts"]),
            "next_attempt_at": next_attempt_at,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def recover_stale_partner_deliveries(*, now: int | None = None) -> dict[str, Any]:
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT proposal_id FROM goia_partnership_outbox
            WHERE status = 'delivering' AND lease_until <= {marker}
            """,
            (timestamp,),
        )
        proposal_ids = [row["proposal_id"] for row in map(dict, cur.fetchall())]
        cur.execute(
            f"""
            UPDATE goia_partnership_outbox
            SET status = 'retryable', lease_token = NULL, lease_until = NULL,
                next_attempt_at = {marker}, last_error_code = 'stale_delivery_lease',
                updated_at = {marker}
            WHERE status = 'delivering' AND lease_until <= {marker}
            """,
            (timestamp, timestamp, timestamp),
        )
        for proposal_id in proposal_ids:
            _insert_partner_delivery_event(
                cur,
                proposal_id=proposal_id,
                event_type="stale_lease_recovered",
                from_status="delivering",
                to_status="retryable",
                reason="stale_delivery_lease",
                now=timestamp,
            )
        conn.commit()
        return {"status": "ok", "recovered_count": len(proposal_ids)}
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def _insert_partner_delivery_event(
    cur,
    *,
    proposal_id: str,
    event_type: str,
    from_status: str | None,
    to_status: str,
    reason: str | None,
    now: int,
) -> None:
    marker = qmark()
    cur.execute(
        f"""
        SELECT COALESCE(MAX(event_order), 0) AS maximum_order
        FROM goia_partnership_delivery_events
        WHERE proposal_id = {marker}
        """,
        (proposal_id,),
    )
    event_order = int(_row(cur.fetchone())["maximum_order"]) + 1
    cur.execute(
        f"""
        INSERT INTO goia_partnership_delivery_events (
            event_id, proposal_id, event_order, event_type,
            from_status, to_status, reason, created_at
        ) VALUES ({", ".join([marker] * 8)})
        """,
        (
            f"gde_{uuid.uuid4().hex}",
            proposal_id,
            event_order,
            event_type,
            from_status,
            to_status,
            reason,
            now,
        ),
    )


def list_partner_delivery_events(
    *,
    proposal_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        if proposal_id:
            cur.execute(
                f"""
                SELECT * FROM goia_partnership_delivery_events
                WHERE proposal_id = {marker}
                ORDER BY event_order ASC, event_id ASC
                LIMIT {marker}
                """,
                (proposal_id, max(1, min(int(limit), 500))),
            )
        else:
            cur.execute(
                f"""
                SELECT * FROM goia_partnership_delivery_events
                ORDER BY created_at DESC, event_id ASC
                LIMIT {marker}
                """,
                (max(1, min(int(limit), 500)),),
            )
        items = list(map(dict, cur.fetchall()))
        return {"status": "ok", "count": len(items), "items": items}
    finally:
        release_conn(conn)


def list_partner_suppressions(*, limit: int = 100) -> dict[str, Any]:
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT * FROM goia_partnership_suppressions
            ORDER BY created_at DESC, domain ASC
            LIMIT {marker}
            """,
            (max(1, min(int(limit), 500)),),
        )
        items = list(map(dict, cur.fetchall()))
        return {
            "status": "ok",
            "count": len(items),
            "items": items,
            "global_precedence": True,
        }
    finally:
        release_conn(conn)


def list_partner_proposals(
    *,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if status is not None and status not in {
        "prepared",
        "delivering",
        "retryable",
        "delivered",
        "failed",
        "expired",
        "cancelled",
    }:
        raise GOIARepositoryError("invalid_proposal_status")
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        query = "SELECT * FROM goia_partnership_outbox"
        params: tuple[Any, ...]
        if status:
            query += f" WHERE status = {marker}"
            params = (status, max(1, min(int(limit), 500)))
        else:
            params = (max(1, min(int(limit), 500)),)
        query += f" ORDER BY created_at DESC, proposal_id ASC LIMIT {marker}"
        cur.execute(query, params)
        items = []
        for row in map(dict, cur.fetchall()):
            row["payload"] = json.loads(row.pop("payload_json"))
            raw_receipt = row.pop("receipt_json")
            row["receipt"] = json.loads(raw_receipt) if raw_receipt else None
            items.append(row)
        return {
            "status": "ok",
            "count": len(items),
            "items": items,
            "delivery_enabled": False,
            "network_access_performed": False,
            "outreach_triggered": False,
        }
    finally:
        release_conn(conn)


def enqueue_sitemap_pages(
    *,
    sitemap_job: dict[str, Any],
    urls: list[str],
    now: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if sitemap_job.get("job_type") != "sitemap":
        raise GOIARepositoryError("sitemap_job_required")
    bounded = max(1, min(int(limit), 500))
    created = []
    duplicates = 0
    for url in urls[:bounded]:
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:24]
        result = enqueue_collection_job(
            provider_id=sitemap_job["provider_id"],
            url=url,
            idempotency_key=f"goia-sitemap:{sitemap_job['job_id']}:{url_hash}",
            job_type="page",
            parent_job_id=sitemap_job["job_id"],
            priority=50,
            now=now,
        )
        if result["state"] == "created":
            created.append(result["job_id"])
        else:
            duplicates += 1
    return {
        "status": "ok",
        "submitted": min(len(urls), bounded),
        "created_count": len(created),
        "duplicate_count": duplicates,
        "truncated": len(urls) > bounded,
        "job_ids": created,
    }


def approve_review_candidate(
    candidate_id: str,
    *,
    observation: OfferObservation,
    reviewer: str,
    reason: str,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT * FROM goia_review_candidates WHERE candidate_id = {marker}",
            (candidate_id,),
        )
        candidate = _row(cur.fetchone())
    finally:
        release_conn(conn)
    if candidate is None:
        raise GOIARepositoryError("candidate_not_found")
    if candidate["status"] == "approved":
        normalized = json.loads(candidate["normalized_json"])
        if normalized != observation.model_dump(mode="json"):
            raise GOIARepositoryError("candidate_approval_conflict")
        return {"candidate_id": candidate_id, "state": "duplicate", "status": "approved"}
    if candidate["status"] != "pending_review":
        raise GOIARepositoryError("candidate_not_pending")
    if observation.merchant_id != candidate["provider_id"]:
        raise GOIARepositoryError("candidate_merchant_mismatch")
    matching_evidence = any(
        str(item.source_url) == candidate["source_url"]
        and item.content_sha256 == candidate["source_sha256"]
        for item in observation.evidence
    )
    if not matching_evidence:
        raise GOIARepositoryError("candidate_evidence_mismatch")

    ingestion = ingest_observation(observation, now=timestamp)
    normalized_json = _canonical_json(observation.model_dump(mode="json"))
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE goia_review_candidates
            SET status = 'approved', normalized_json = {marker},
                reviewer = {marker}, reason = {marker}, reviewed_at = {marker},
                updated_at = {marker}
            WHERE candidate_id = {marker} AND status = 'pending_review'
            """,
            (
                normalized_json,
                reviewer,
                reason,
                timestamp,
                timestamp,
                candidate_id,
            ),
        )
        if cur.rowcount != 1:
            raise GOIARepositoryError("candidate_approval_race")
        conn.commit()
        return {
            "candidate_id": candidate_id,
            "state": "approved",
            "status": "approved",
            "observation": ingestion,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def reject_review_candidate(
    candidate_id: str,
    *,
    reviewer: str,
    reason: str,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT status, reviewer, reason FROM goia_review_candidates WHERE candidate_id = {marker}",
            (candidate_id,),
        )
        candidate = _row(cur.fetchone())
        if candidate is None:
            raise GOIARepositoryError("candidate_not_found")
        if candidate["status"] == "rejected":
            if candidate["reviewer"] != reviewer or candidate["reason"] != reason:
                raise GOIARepositoryError("candidate_rejection_conflict")
            return {"candidate_id": candidate_id, "state": "duplicate", "status": "rejected"}
        if candidate["status"] != "pending_review":
            raise GOIARepositoryError("candidate_not_pending")
        cur.execute(
            f"""
            UPDATE goia_review_candidates
            SET status = 'rejected', reviewer = {marker}, reason = {marker},
                reviewed_at = {marker}, updated_at = {marker}
            WHERE candidate_id = {marker} AND status = 'pending_review'
            """,
            (reviewer, reason, timestamp, timestamp, candidate_id),
        )
        conn.commit()
        return {"candidate_id": candidate_id, "state": "rejected", "status": "rejected"}
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)
