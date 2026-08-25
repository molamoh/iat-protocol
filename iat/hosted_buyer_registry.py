"""Shared registry for hosted multi-tenant buyer runtimes.

The registry stores public identity and connector references only. Runtime
tokens, wallet keys and delivered payloads never belong in this table.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from solders.pubkey import Pubkey

from iat.api import db


_CONNECTOR_ID = re.compile(r"^[A-Za-z0-9_.:-]{3,160}$")
_STATUSES = {"active", "paused", "revoked"}


def _wallet(value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = Pubkey.from_string(raw)
    except Exception as exc:
        raise ValueError("buyer_wallet_invalid") from exc
    if str(parsed) != raw:
        raise ValueError("buyer_wallet_invalid")
    return raw


def _connector(value: str) -> str:
    raw = str(value or "").strip()
    if not _CONNECTOR_ID.fullmatch(raw):
        raise ValueError("runtime_connector_id_invalid")
    return raw


def init_hosted_buyer_registry_db() -> None:
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS hosted_buyer_agents (
                buyer_agent_id TEXT PRIMARY KEY,
                buyer_wallet TEXT NOT NULL,
                runtime_connector_id TEXT NOT NULL,
                cluster TEXT NOT NULL DEFAULT 'solana:devnet',
                status TEXT NOT NULL DEFAULT 'active',
                policy_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                last_heartbeat_at INTEGER
            )
            """
        )
        cur.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_hosted_buyer_identity
               ON hosted_buyer_agents(buyer_wallet, runtime_connector_id)"""
        )
        cur.execute(
            """CREATE INDEX IF NOT EXISTS idx_hosted_buyer_status_heartbeat
               ON hosted_buyer_agents(status, last_heartbeat_at)"""
        )
        conn.commit()
    finally:
        db.release_conn(conn)


def register_hosted_buyer_agent(
    *,
    buyer_wallet: str,
    runtime_connector_id: str,
    policy: dict[str, Any] | None = None,
    cluster: str = "solana:devnet",
    now: int | None = None,
) -> dict[str, Any]:
    wallet = _wallet(buyer_wallet)
    connector = _connector(runtime_connector_id)
    if cluster != "solana:devnet":
        raise ValueError("buyer_cluster_not_allowed")
    if policy is not None and not isinstance(policy, dict):
        raise ValueError("buyer_policy_invalid")
    current = int(time.time()) if now is None else int(now)
    payload = json.dumps(policy or {}, sort_keys=True, separators=(",", ":"))
    init_hosted_buyer_registry_db()
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"""SELECT * FROM hosted_buyer_agents
                WHERE buyer_wallet={p} AND runtime_connector_id={p}""",
            (wallet, connector),
        )
        existing = cur.fetchone()
        if existing:
            return _public(dict(existing))
        agent_id = "bya_" + uuid.uuid4().hex
        cur.execute(
            f"""INSERT INTO hosted_buyer_agents (
                buyer_agent_id, buyer_wallet, runtime_connector_id, cluster,
                status, policy_json, created_at, updated_at, last_heartbeat_at
            ) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},NULL)""",
            (agent_id, wallet, connector, cluster, "active", payload, current, current),
        )
        conn.commit()
        cur.execute(
            f"SELECT * FROM hosted_buyer_agents WHERE buyer_agent_id={p}",
            (agent_id,),
        )
        return _public(dict(cur.fetchone()))
    except Exception:
        conn.rollback()
        raise
    finally:
        db.release_conn(conn)


def heartbeat_hosted_buyer_agent(
    buyer_agent_id: str, *, status: str = "active", now: int | None = None
) -> dict[str, Any] | None:
    if status not in _STATUSES:
        raise ValueError("buyer_agent_status_invalid")
    current = int(time.time()) if now is None else int(now)
    init_hosted_buyer_registry_db()
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"""UPDATE hosted_buyer_agents
                SET status={p}, updated_at={p}, last_heartbeat_at={p}
                WHERE buyer_agent_id={p}""",
            (status, current, current, buyer_agent_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        cur.execute(
            f"SELECT * FROM hosted_buyer_agents WHERE buyer_agent_id={p}",
            (buyer_agent_id,),
        )
        return _public(dict(cur.fetchone()))
    finally:
        db.release_conn(conn)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    try:
        policy = json.loads(row.get("policy_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        policy = {}
    return {
        "buyer_agent_id": row.get("buyer_agent_id"),
        "buyer_wallet": row.get("buyer_wallet"),
        "runtime_connector_id": row.get("runtime_connector_id"),
        "cluster": row.get("cluster"),
        "status": row.get("status"),
        "policy": policy,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "last_heartbeat_at": row.get("last_heartbeat_at"),
    }
