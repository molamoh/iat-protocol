"""Persistence for the isolated GOIA commercial index."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from iat.api.db import get_conn, qmark, release_conn
from iat.goia.contracts import MerchantProviderManifest, OfferObservation


class GOIARepositoryError(ValueError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode()).hexdigest()


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


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
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_goia_collection_jobs_status
            ON goia_collection_jobs(status, created_at)
            """
        )
        conn.commit()
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
    url: str,
    idempotency_key: str,
    now: int | None = None,
) -> dict[str, Any]:
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
            if existing["url"] != url:
                raise GOIARepositoryError("collection_idempotency_conflict")
            return {
                "job_id": existing["job_id"],
                "state": "duplicate",
                "status": existing["status"],
            }
        job_id = f"goj_{uuid.uuid4().hex}"
        cur.execute(
            f"""
            INSERT INTO goia_collection_jobs (
                job_id, idempotency_key, url, status, attempts,
                created_at, updated_at
            ) VALUES ({", ".join([marker] * 7)})
            """,
            (job_id, idempotency_key, url, "queued", 0, timestamp, timestamp),
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
                ORDER BY created_at ASC, job_id ASC
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
        status="review_required",
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
        return {
            "status": "ok",
            "jobs": {
                "queued": counts.get("queued", 0),
                "processing": counts.get("processing", 0),
                "review_required": counts.get("review_required", 0),
                "failed": counts.get("failed", 0),
            },
            "automatic_publication": False,
        }
    finally:
        release_conn(conn)
