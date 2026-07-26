"""Persistence for the isolated GOIA commercial index."""

from __future__ import annotations

import hashlib
import json
import time
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
