"""Credential rotation and authentication for hosted buyer connectors."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from iat.api import db
from iat.hosted_buyer_registry import init_hosted_buyer_registry_db


def init_hosted_buyer_connector_db() -> None:
    init_hosted_buyer_registry_db()
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS hosted_buyer_connector_credentials (
                credential_id TEXT PRIMARY KEY,
                buyer_agent_id TEXT NOT NULL,
                key_digest TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL,
                last_used_at INTEGER,
                revoked_at INTEGER
            )"""
        )
        cur.execute(
            """CREATE INDEX IF NOT EXISTS idx_hosted_buyer_connector_agent
               ON hosted_buyer_connector_credentials(buyer_agent_id, status)"""
        )
        conn.commit()
    finally:
        db.release_conn(conn)


def rotate_hosted_buyer_connector_key(
    buyer_agent_id: str, *, now: int | None = None
) -> dict[str, Any]:
    current = int(time.time()) if now is None else int(now)
    init_hosted_buyer_connector_db()
    key = "ibc_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(key.encode()).hexdigest()
    credential_id = "ibc_cred_" + secrets.token_hex(12)
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"UPDATE hosted_buyer_connector_credentials SET status='revoked', revoked_at={p} "
            f"WHERE buyer_agent_id={p} AND status='active'", (current, buyer_agent_id)
        )
        cur.execute(
            f"INSERT INTO hosted_buyer_connector_credentials "
            f"(credential_id, buyer_agent_id, key_digest, status, created_at) VALUES ({p},{p},{p},'active',{p})",
            (credential_id, buyer_agent_id, digest, current),
        )
        conn.commit()
        return {
            "status": "rotated",
            "credential_id": credential_id,
            "buyer_agent_id": buyer_agent_id,
            "connector_key": key,
            "created_at": current,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        db.release_conn(conn)


def authenticate_hosted_buyer_connector(
    connector_key: str, *, now: int | None = None
) -> dict[str, Any] | None:
    value = str(connector_key or "")
    if not value.startswith("ibc_"):
        return None
    digest = hashlib.sha256(value.encode()).hexdigest()
    current = int(time.time()) if now is None else int(now)
    init_hosted_buyer_connector_db()
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"""SELECT c.credential_id, c.buyer_agent_id, a.status, a.buyer_wallet,
                       a.runtime_connector_id
                FROM hosted_buyer_connector_credentials c
                JOIN hosted_buyer_agents a ON a.buyer_agent_id=c.buyer_agent_id
                WHERE c.key_digest={p} AND c.status='active'""",
            (digest,),
        )
        row = cur.fetchone()
        if not row:
            return None
        item = dict(row)
        if item.get("status") != "active":
            return None
        cur.execute(
            f"UPDATE hosted_buyer_connector_credentials SET last_used_at={p} WHERE credential_id={p}",
            (current, item["credential_id"]),
        )
        conn.commit()
        return {
            "credential_id": item["credential_id"],
            "buyer_agent_id": item["buyer_agent_id"],
            "buyer_wallet": item["buyer_wallet"],
            "runtime_connector_id": item["runtime_connector_id"],
        }
    finally:
        db.release_conn(conn)
