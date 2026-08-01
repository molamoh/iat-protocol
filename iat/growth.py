"""Autonomous, governed acquisition engine for machine-to-machine adoption."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

from iat.api.db import get_conn, qmark, release_conn
from iat.security.network import UnsafeNetworkTarget, validate_public_runtime_url


PROSPECT_STATUSES = {"discovered", "qualified", "nurturing", "converted", "rejected"}
CAMPAIGN_STATUSES = {"draft", "active", "paused", "completed"}
ACTION_STATUSES = {"proposed", "approved", "executing", "executed", "blocked", "failed"}
SEGMENTS = {"ai_agent", "agent_platform", "marketplace", "framework", "seller", "unknown"}
_loop_lock = threading.Lock()
_outreach_lock = threading.Lock()
_loop_started = False
MAX_DISCOVERY_FEED_BYTES = 1_000_000
MAX_DISCOVERY_CANDIDATES = 100
PROSPECT_OUTREACH_COOLDOWN_SECONDS = 24 * 60 * 60


class GrowthValidationError(ValueError):
    pass


def _now() -> int:
    return int(time.time())


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def _response_token(*, action_id_seed: str, secret: str) -> str:
    return hmac.new(
        secret.encode(),
        action_id_seed.encode(),
        hashlib.sha256,
    ).hexdigest()


def _row(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key, fallback in (
        ("signals", {}),
        ("metadata", {}),
        ("payload", {}),
        ("policy", {}),
        ("evidence", {}),
        ("proposed_policy", {}),
        ("previous_policy", {}),
    ):
        if key in result:
            result[key] = _decode(result[key], fallback)
    return result


def canonicalize_prospect_url(url: str) -> str:
    raw = str(url or "").strip()
    if len(raw) > 2_000:
        raise GrowthValidationError("prospect_url_too_long")
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise GrowthValidationError("valid_http_prospect_url_required")
    if parsed.username or parsed.password or parsed.fragment:
        raise GrowthValidationError("unsafe_prospect_url")
    hostname = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    netloc = hostname
    if port and not ((parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def init_growth_tables() -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_prospects (
                prospect_id TEXT PRIMARY KEY,
                canonical_url TEXT NOT NULL UNIQUE,
                domain TEXT NOT NULL,
                name TEXT NOT NULL,
                segment TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                signals TEXT NOT NULL,
                metadata TEXT NOT NULL,
                next_action_at INTEGER,
                last_contacted_at INTEGER,
                contact_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_campaigns (
                campaign_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                target_segment TEXT NOT NULL,
                min_score REAL NOT NULL,
                daily_action_limit INTEGER NOT NULL,
                policy TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_actions (
                action_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                prospect_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                channel TEXT NOT NULL,
                status TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                payload TEXT NOT NULL,
                reason TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                response_code INTEGER,
                response_excerpt TEXT,
                scheduled_at INTEGER NOT NULL,
                executed_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_events (
                event_id TEXT PRIMARY KEY,
                prospect_id TEXT,
                campaign_id TEXT,
                action_id TEXT,
                event_type TEXT NOT NULL,
                value REAL NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_responses (
                response_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                action_id TEXT NOT NULL,
                prospect_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                response_type TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_suppressions (
                suppression_id TEXT PRIMARY KEY,
                prospect_id TEXT,
                domain TEXT,
                reason TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(prospect_id),
                UNIQUE(domain)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_recommendations (
                recommendation_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                recommendation_type TEXT NOT NULL,
                status TEXT NOT NULL,
                evidence TEXT NOT NULL,
                proposed_policy TEXT NOT NULL,
                previous_policy TEXT,
                created_at INTEGER NOT NULL,
                applied_at INTEGER,
                rolled_back_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_outreach_windows (
                prospect_id TEXT PRIMARY KEY,
                action_id TEXT NOT NULL,
                reserved_at INTEGER NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_growth_prospects_status_score ON growth_prospects(status, score)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_growth_actions_status_schedule ON growth_actions(status, scheduled_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_growth_events_type_created ON growth_events(event_type, created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_growth_responses_campaign_type ON growth_responses(campaign_id, response_type)")
        conn.commit()
    finally:
        release_conn(conn)


def record_growth_event(
    event_type: str,
    *,
    prospect_id: str | None = None,
    campaign_id: str | None = None,
    action_id: str | None = None,
    value: float = 0,
    metadata: dict | None = None,
) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    event_id = f"gevt_{uuid.uuid4().hex}"
    try:
        p = qmark()
        cur.execute(
            f"""INSERT INTO growth_events
            (event_id, prospect_id, campaign_id, action_id, event_type, value, metadata, created_at)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p})""",
            (event_id, prospect_id, campaign_id, action_id, event_type, float(value), _json(metadata or {}), _now()),
        )
        conn.commit()
        return {"status": "recorded", "event_id": event_id}
    finally:
        release_conn(conn)


def upsert_prospect(
    *,
    url: str,
    name: str = "",
    segment: str = "unknown",
    source: str = "manual",
    metadata: dict | None = None,
) -> dict:
    canonical_url = canonicalize_prospect_url(url)
    parsed = urlparse(canonical_url)
    segment = segment if segment in SEGMENTS else "unknown"
    metadata = metadata if isinstance(metadata, dict) else {}
    clean_name = str(name or parsed.hostname)[:200]
    clean_source = str(source or "manual")[:120]
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(f"SELECT * FROM growth_prospects WHERE canonical_url = {p}", (canonical_url,))
        existing = cur.fetchone()
        now = _now()
        if existing:
            current = _row(existing)
            merged = {**current.get("metadata", {}), **metadata}
            cur.execute(
                f"""UPDATE growth_prospects SET name={p}, segment={p}, source={p},
                metadata={p}, updated_at={p} WHERE prospect_id={p}""",
                (clean_name, segment, clean_source, _json(merged), now, current["prospect_id"]),
            )
            prospect_id = current["prospect_id"]
            created = False
        else:
            prospect_id = f"gpro_{uuid.uuid4().hex}"
            cur.execute(
                f"""INSERT INTO growth_prospects
                (prospect_id, canonical_url, domain, name, segment, source, status, score,
                 signals, metadata, next_action_at, created_at, updated_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})""",
                (
                    prospect_id, canonical_url, parsed.hostname, clean_name, segment,
                    clean_source, "discovered", 0.0, _json({}), _json(metadata), now, now, now,
                ),
            )
            created = True
        conn.commit()
    finally:
        release_conn(conn)
    if created:
        record_growth_event("prospect_discovered", prospect_id=prospect_id, metadata={"source": clean_source})
    return {"status": "created" if created else "updated", "prospect_id": prospect_id, "canonical_url": canonical_url}


def discover_from_feed(feed_url: str) -> dict:
    """Import bounded candidates from an explicitly configured machine registry."""
    canonical_feed = canonicalize_prospect_url(feed_url)
    try:
        target = validate_public_runtime_url(canonical_feed)
    except UnsafeNetworkTarget as exc:
        raise GrowthValidationError(str(exc)) from exc
    allowlist = {
        host.strip().lower()
        for host in os.getenv("IAT_GROWTH_DISCOVERY_HOSTS", "").split(",")
        if host.strip()
    }
    if allowlist and target["hostname"] not in allowlist:
        raise GrowthValidationError("discovery_feed_host_not_allowed")

    try:
        response = requests.get(
            canonical_feed,
            headers={
                "Accept": "application/json",
                "User-Agent": "IAT-Growth-Discovery/1.0",
            },
            timeout=(3.05, 15),
            allow_redirects=False,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise GrowthValidationError(f"discovery_feed_unavailable:{type(exc).__name__}") from exc
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_DISCOVERY_FEED_BYTES:
                raise GrowthValidationError("discovery_feed_too_large")
        except ValueError as exc:
            raise GrowthValidationError("discovery_feed_invalid_content_length") from exc
    if len(response.content) > MAX_DISCOVERY_FEED_BYTES:
        raise GrowthValidationError("discovery_feed_too_large")
    try:
        document = response.json()
    except ValueError as exc:
        raise GrowthValidationError("discovery_feed_invalid_json") from exc
    candidates = document.get("candidates", []) if isinstance(document, dict) else document
    if not isinstance(candidates, list):
        raise GrowthValidationError("discovery_feed_candidates_required")

    imported = rejected = 0
    results = []
    for candidate in candidates[:MAX_DISCOVERY_CANDIDATES]:
        if not isinstance(candidate, dict):
            rejected += 1
            continue
        try:
            result = upsert_prospect(
                url=candidate.get("url"),
                name=candidate.get("name", ""),
                segment=candidate.get("segment", "unknown"),
                source=f"feed:{target['hostname']}",
                metadata=candidate.get("metadata", {}),
            )
            imported += 1
            results.append(result)
        except (GrowthValidationError, TypeError):
            rejected += 1
    record_growth_event(
        "discovery_feed_processed",
        metadata={
            "feed_host": target["hostname"],
            "imported": imported,
            "rejected": rejected,
            "truncated": len(candidates) > MAX_DISCOVERY_CANDIDATES,
        },
    )
    return {
        "status": "processed",
        "feed_host": target["hostname"],
        "imported": imported,
        "rejected": rejected,
        "truncated": len(candidates) > MAX_DISCOVERY_CANDIDATES,
        "results": results,
    }


def get_prospect(prospect_id: str) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(f"SELECT * FROM growth_prospects WHERE prospect_id = {p}", (prospect_id,))
        found = cur.fetchone()
        return _row(found) if found else None
    finally:
        release_conn(conn)


def get_prospect_by_url(url: str) -> dict | None:
    canonical_url = canonicalize_prospect_url(url)
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(
            f"SELECT * FROM growth_prospects WHERE canonical_url = {p}",
            (canonical_url,),
        )
        found = cur.fetchone()
        return _row(found) if found else None
    finally:
        release_conn(conn)


def register_inbound_pilot(
    *,
    url: str,
    name: str,
    segment: str,
    use_case: str,
    source: str = "direct",
    referral: str = "",
    outreach_opt_in: bool,
) -> dict:
    """Register a voluntary pilot applicant and qualify it without outreach."""
    if outreach_opt_in is not True:
        raise GrowthValidationError("pilot_outreach_consent_required")
    clean_use_case = str(use_case or "").strip()
    if len(clean_use_case) < 10:
        raise GrowthValidationError("pilot_use_case_required")
    if segment not in SEGMENTS:
        raise GrowthValidationError("unsupported_pilot_segment")

    canonical_url = canonicalize_prospect_url(url)
    existing = get_prospect_by_url(canonical_url)
    registered_at = int(
        (existing or {}).get("metadata", {}).get("pilot_registered_at") or _now()
    )
    result = upsert_prospect(
        url=canonical_url,
        name=name,
        segment=segment,
        source="inbound_pilot",
        metadata={
            "description": clean_use_case[:1_000],
            "outreach_opt_in": True,
            "pilot_registered_at": registered_at,
            "acquisition_source": str(source or "direct")[:80],
            "referral": str(referral or "")[:120],
        },
    )
    qualification = qualify_prospect(result["prospect_id"])
    if not existing or not existing.get("metadata", {}).get("pilot_registered_at"):
        record_growth_event(
            "conversion_pilot_application",
            prospect_id=result["prospect_id"],
            metadata={
                "source": str(source or "direct")[:80],
                "referral": str(referral or "")[:120],
            },
        )
    return {
        "status": "accepted" if not existing else "already_registered",
        "pilot_id": result["prospect_id"],
        "qualification": {
            "status": qualification["status"],
            "score": qualification["score"],
        },
        "checkout_asset": "USDC",
        "settlement_asset": "IAT",
        "network": "solana-devnet",
        "next_steps": [
            {"rel": "discover", "method": "GET", "href": "/.well-known/iat.json"},
            {"rel": "capabilities", "method": "GET", "href": "/v1/capabilities"},
            {"rel": "sandbox", "method": "GET", "href": "/sandbox/v1/offers"},
            {
                "rel": "create_checkout_quote",
                "method": "POST",
                "href": "/payments/v1/universal/quote",
            },
        ],
    }


def suppress_prospect(
    *,
    prospect_id: str | None = None,
    domain: str | None = None,
    reason: str,
    source: str,
) -> dict:
    prospect = get_prospect(prospect_id) if prospect_id else None
    domain = str(domain or (prospect or {}).get("domain") or "").strip().lower()
    if not prospect_id and not domain:
        raise GrowthValidationError("prospect_id_or_domain_required")
    if len(str(reason).strip()) < 3:
        raise GrowthValidationError("suppression_reason_required")
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        clauses = []
        params = []
        if prospect_id:
            clauses.append(f"prospect_id={p}")
            params.append(prospect_id)
        if domain:
            clauses.append(f"domain={p}")
            params.append(domain)
        cur.execute(
            f"SELECT * FROM growth_suppressions WHERE {' OR '.join(clauses)} LIMIT 1",
            tuple(params),
        )
        existing = cur.fetchone()
        if existing:
            return {"status": "already_suppressed", "suppression": dict(existing)}
        suppression_id = f"gsup_{uuid.uuid4().hex}"
        cur.execute(
            f"""INSERT INTO growth_suppressions
            (suppression_id, prospect_id, domain, reason, source, created_at)
            VALUES ({p},{p},{p},{p},{p},{p})""",
            (
                suppression_id, prospect_id, domain or None, str(reason)[:500],
                str(source)[:120], _now(),
            ),
        )
        if prospect_id:
            cur.execute(
                f"UPDATE growth_prospects SET status={p}, updated_at={p} WHERE prospect_id={p}",
                ("rejected", _now(), prospect_id),
            )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event(
        "prospect_suppressed",
        prospect_id=prospect_id,
        metadata={"domain": domain, "reason": reason, "source": source},
    )
    return {"status": "suppressed", "suppression_id": suppression_id}


def is_prospect_suppressed(prospect: dict) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(
            f"""SELECT suppression_id FROM growth_suppressions
            WHERE prospect_id={p} OR domain={p} LIMIT 1""",
            (prospect["prospect_id"], prospect["domain"]),
        )
        return cur.fetchone() is not None
    finally:
        release_conn(conn)


def list_suppressions(*, limit: int = 100) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        limit = max(1, min(int(limit), 500))
        cur.execute(f"SELECT * FROM growth_suppressions ORDER BY created_at DESC LIMIT {limit}")
        items = [dict(item) for item in cur.fetchall()]
        return {"status": "ok", "count": len(items), "suppressions": items}
    finally:
        release_conn(conn)


def list_prospects(*, status: str | None = None, limit: int = 100) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        limit = max(1, min(int(limit), 500))
        if status:
            cur.execute(
                f"SELECT * FROM growth_prospects WHERE status={p} ORDER BY score DESC, created_at DESC LIMIT {limit}",
                (status,),
            )
        else:
            cur.execute(f"SELECT * FROM growth_prospects ORDER BY score DESC, created_at DESC LIMIT {limit}")
        rows = [_row(item) for item in cur.fetchall()]
        return {"status": "ok", "count": len(rows), "prospects": rows}
    finally:
        release_conn(conn)


PUBLIC_OUTREACH_PERMISSION_SOURCES = {
    "agent_manifest",
    "machine_registry",
    "published_outreach_endpoint",
}


def outreach_authorization(prospect: dict) -> dict:
    """Return a fail-closed, auditable authorization decision."""
    metadata = prospect.get("metadata", {})
    if metadata.get("do_not_contact") is True:
        return {"authorized": False, "reason": "do_not_contact"}
    if metadata.get("outreach_opt_in") is True:
        return {
            "authorized": True,
            "reason": "explicit_opt_in",
            "evidence": {"source": "explicit_opt_in"},
        }
    permission = metadata.get("outreach_permission")
    if not isinstance(permission, dict) or permission.get("allowed") is not True:
        return {"authorized": False, "reason": "authorization_required"}
    source = str(permission.get("source") or "")
    evidence_url = str(permission.get("evidence_url") or "")
    observed_at = permission.get("observed_at")
    if source not in PUBLIC_OUTREACH_PERMISSION_SOURCES:
        return {"authorized": False, "reason": "untrusted_permission_source"}
    try:
        evidence = canonicalize_prospect_url(evidence_url)
    except (GrowthValidationError, TypeError):
        return {"authorized": False, "reason": "invalid_permission_evidence"}
    if urlparse(evidence).hostname != prospect.get("domain"):
        return {"authorized": False, "reason": "permission_domain_mismatch"}
    if not isinstance(observed_at, int) or observed_at <= 0:
        return {"authorized": False, "reason": "permission_observation_required"}
    return {
        "authorized": True,
        "reason": "verified_public_permission",
        "evidence": {
            "source": source,
            "evidence_url": evidence,
            "observed_at": observed_at,
        },
    }


def qualify_prospect(prospect_id: str) -> dict:
    prospect = get_prospect(prospect_id)
    if not prospect:
        raise GrowthValidationError("prospect_not_found")
    metadata = prospect.get("metadata", {})
    text = " ".join(
        str(value).lower()
        for value in (
            prospect.get("name"), prospect.get("domain"), prospect.get("segment"),
            metadata.get("description"), metadata.get("capabilities"), metadata.get("tags"),
        )
    )
    authorization = outreach_authorization(prospect)
    signals: dict[str, Any] = {
        "https": prospect["canonical_url"].startswith("https://"),
        "machine_interface": any(term in text for term in ("api", "agent", "mcp", "ai", "llm")),
        "commerce_relevance": any(term in text for term in ("commerce", "payment", "market", "seller", "buyer")),
        "integration_evidence": bool(metadata.get("openapi_url") or metadata.get("manifest_url")),
        "explicit_opt_in": metadata.get("outreach_opt_in") is True,
        "public_outreach_permission": authorization["reason"] == "verified_public_permission",
        "outreach_authorized": authorization["authorized"],
        "blocked": metadata.get("do_not_contact") is True,
    }
    score = 10.0
    score += 15 if signals["https"] else 0
    score += 25 if signals["machine_interface"] else 0
    score += 20 if signals["commerce_relevance"] else 0
    score += 15 if signals["integration_evidence"] else 0
    score += 15 if signals["outreach_authorized"] else 0
    if prospect["segment"] != "unknown":
        score += 10
    if signals["blocked"]:
        score = 0
    score = round(max(0.0, min(score, 100.0)), 2)
    status = "rejected" if signals["blocked"] else ("qualified" if score >= 50 else "discovered")
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(
            f"UPDATE growth_prospects SET score={p}, signals={p}, status={p}, updated_at={p} WHERE prospect_id={p}",
            (score, _json(signals), status, _now(), prospect_id),
        )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event("prospect_qualified", prospect_id=prospect_id, value=score, metadata={"status": status})
    return {"status": status, "prospect_id": prospect_id, "score": score, "signals": signals}


def create_campaign(
    *,
    name: str,
    target_segment: str = "unknown",
    min_score: float = 60,
    daily_action_limit: int = 25,
    policy: dict | None = None,
) -> dict:
    if not str(name or "").strip():
        raise GrowthValidationError("campaign_name_required")
    if target_segment not in SEGMENTS:
        raise GrowthValidationError("unsupported_target_segment")
    if not 0 <= float(min_score) <= 100:
        raise GrowthValidationError("invalid_min_score")
    if not 1 <= int(daily_action_limit) <= 1_000:
        raise GrowthValidationError("invalid_daily_action_limit")
    campaign_id = f"gcam_{uuid.uuid4().hex}"
    now = _now()
    safe_policy = {
        "channel": "machine_webhook",
        "require_opt_in": True,
        "require_manual_action_approval": True,
        "auto_execute_approved_opt_in": False,
        **(policy or {}),
    }
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(
            f"""INSERT INTO growth_campaigns
            (campaign_id, name, status, target_segment, min_score, daily_action_limit, policy, created_at, updated_at)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p})""",
            (
                campaign_id, str(name).strip()[:200], "draft", target_segment,
                float(min_score), int(daily_action_limit), _json(safe_policy), now, now,
            ),
        )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event("campaign_created", campaign_id=campaign_id)
    return {"status": "created", "campaign_id": campaign_id, "policy": safe_policy}


def set_campaign_status(campaign_id: str, status: str) -> dict:
    if status not in CAMPAIGN_STATUSES:
        raise GrowthValidationError("invalid_campaign_status")
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(f"UPDATE growth_campaigns SET status={p}, updated_at={p} WHERE campaign_id={p}", (status, _now(), campaign_id))
        if cur.rowcount != 1:
            raise GrowthValidationError("campaign_not_found")
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event("campaign_status_changed", campaign_id=campaign_id, metadata={"status": status})
    return {"status": status, "campaign_id": campaign_id}


def _campaign(campaign_id: str) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(f"SELECT * FROM growth_campaigns WHERE campaign_id={p}", (campaign_id,))
        found = cur.fetchone()
        return _row(found) if found else None
    finally:
        release_conn(conn)


def list_campaigns(*, limit: int = 100) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        limit = max(1, min(int(limit), 500))
        cur.execute(f"SELECT * FROM growth_campaigns ORDER BY created_at DESC LIMIT {limit}")
        campaigns = [_row(item) for item in cur.fetchall()]
        return {"status": "ok", "count": len(campaigns), "campaigns": campaigns}
    finally:
        release_conn(conn)


def list_actions(*, status: str | None = None, limit: int = 100) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        limit = max(1, min(int(limit), 500))
        if status:
            cur.execute(
                f"SELECT * FROM growth_actions WHERE status={p} ORDER BY created_at DESC LIMIT {limit}",
                (status,),
            )
        else:
            cur.execute(f"SELECT * FROM growth_actions ORDER BY created_at DESC LIMIT {limit}")
        actions = [_row(item) for item in cur.fetchall()]
        return {"status": "ok", "count": len(actions), "actions": actions}
    finally:
        release_conn(conn)


def domain_delivery_health(domain: str) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(
            f"""SELECT a.status
            FROM growth_actions a
            JOIN growth_prospects p ON p.prospect_id = a.prospect_id
            WHERE p.domain={p} AND a.attempts>0
            ORDER BY a.updated_at DESC
            LIMIT 5""",
            (domain,),
        )
        recent = [str(dict(item)["status"]) for item in cur.fetchall()]
    finally:
        release_conn(conn)
    consecutive_failures = 0
    for status in recent:
        if status != "failed":
            break
        consecutive_failures += 1
    return {
        "allowed": consecutive_failures < 3,
        "consecutive_failures": consecutive_failures,
        "circuit": "open" if consecutive_failures >= 3 else "closed",
    }


def recover_stale_actions(*, stale_after_seconds: int = 300) -> dict:
    cutoff = _now() - max(60, int(stale_after_seconds))
    conn = get_conn()
    cur = conn.cursor()
    recovered = []
    try:
        p = qmark()
        cur.execute(
            f"SELECT * FROM growth_actions WHERE status={p} AND updated_at<{p}",
            ("executing", cutoff),
        )
        stale = [_row(item) for item in cur.fetchall()]
        now = _now()
        for action in stale:
            cur.execute(
                f"""UPDATE growth_actions SET status={p}, reason={p},
                response_excerpt={p}, updated_at={p} WHERE action_id={p} AND status={p}""",
                (
                    "failed", "stale_execution_recovered",
                    "worker terminated before delivery result", now,
                    action["action_id"], "executing",
                ),
            )
            if cur.rowcount == 1:
                recovered.append(action)
        conn.commit()
    finally:
        release_conn(conn)
    for action in recovered:
        record_growth_event(
            "action_stale_recovered",
            prospect_id=action["prospect_id"],
            campaign_id=action["campaign_id"],
            action_id=action["action_id"],
        )
    return {"status": "completed", "recovered": len(recovered)}


def prospect_outreach_eligibility(prospect_id: str, *, now: int | None = None) -> dict:
    """Enforce one prospecting attempt per prospect in any rolling 24-hour window."""
    prospect = get_prospect(prospect_id)
    if not prospect:
        raise GrowthValidationError("prospect_not_found")
    now = int(now or _now())
    cutoff = now - PROSPECT_OUTREACH_COOLDOWN_SECONDS
    timestamps = [
        int(value)
        for value in (prospect.get("last_contacted_at"),)
        if value is not None
    ]
    latest_action_id = None
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(
            f"""SELECT action_id, created_at AS latest
            FROM growth_actions
            WHERE prospect_id={p}
              AND status IN ('proposed','approved','executing','executed','failed')
              AND created_at>{p}
            ORDER BY created_at DESC, action_id DESC
            LIMIT 1""",
            (prospect_id, cutoff),
        )
        latest_row = cur.fetchone()
        latest_action = dict(latest_row).get("latest") if latest_row else None
        if latest_action is not None:
            timestamps.append(int(latest_action))
            latest_action_id = dict(latest_row).get("action_id")
        cur.execute(
            f"SELECT action_id, reserved_at FROM growth_outreach_windows WHERE prospect_id={p}",
            (prospect_id,),
        )
        window = cur.fetchone()
        if window and int(dict(window)["reserved_at"]) > cutoff:
            timestamps.append(int(dict(window)["reserved_at"]))
            latest_action_id = dict(window)["action_id"]
    finally:
        release_conn(conn)
    latest = max(timestamps) if timestamps else None
    if latest is not None and now - latest < PROSPECT_OUTREACH_COOLDOWN_SECONDS:
        return {
            "eligible": False,
            "reason": "prospect_24h_cooldown",
            "last_outreach_at": latest,
            "latest_action_id": latest_action_id,
            "next_eligible_at": latest + PROSPECT_OUTREACH_COOLDOWN_SECONDS,
            "cooldown_seconds": PROSPECT_OUTREACH_COOLDOWN_SECONDS,
        }
    return {
        "eligible": True,
        "reason": "outreach_window_available",
        "last_outreach_at": latest,
        "latest_action_id": latest_action_id,
        "next_eligible_at": now,
        "cooldown_seconds": PROSPECT_OUTREACH_COOLDOWN_SECONDS,
    }


def propose_action(prospect_id: str, campaign_id: str) -> dict:
    prospect = get_prospect(prospect_id)
    campaign = _campaign(campaign_id)
    if not prospect or not campaign:
        raise GrowthValidationError("prospect_or_campaign_not_found")
    if campaign["status"] != "active":
        raise GrowthValidationError("campaign_not_active")
    if prospect["status"] == "rejected" or prospect["score"] < campaign["min_score"]:
        return {"status": "skipped", "reason": "prospect_not_eligible"}
    if is_prospect_suppressed(prospect):
        return {"status": "blocked", "reason": "prospect_suppressed"}
    domain_health = domain_delivery_health(prospect["domain"])
    if not domain_health["allowed"]:
        return {
            "status": "skipped",
            "reason": "domain_delivery_circuit_open",
            "consecutive_failures": domain_health["consecutive_failures"],
        }
    if campaign["target_segment"] != "unknown" and prospect["segment"] != campaign["target_segment"]:
        return {"status": "skipped", "reason": "segment_mismatch"}
    eligibility = prospect_outreach_eligibility(prospect_id)
    if not eligibility["eligible"]:
        return {
            "status": "skipped",
            "reason": eligibility["reason"],
            "next_eligible_at": eligibility["next_eligible_at"],
        }

    metadata = prospect.get("metadata", {})
    policy = campaign.get("policy", {})
    authorization = outreach_authorization(prospect)
    opt_in = authorization["authorized"]
    blocked = metadata.get("do_not_contact") is True
    risk = "low" if opt_in else "high"
    status = "proposed"
    reason = "manual_approval_required"
    if blocked:
        status, reason = "blocked", "do_not_contact"
    elif policy.get("require_opt_in", True) and not opt_in:
        status, reason = "blocked", authorization["reason"]

    endpoint = metadata.get("outreach_endpoint") or prospect["canonical_url"]
    action_id = f"gact_{uuid.uuid4().hex}"
    variants = policy.get("variants") if isinstance(policy.get("variants"), list) else []
    valid_variants = [
        item for item in variants[:10]
        if isinstance(item, dict) and item.get("id") and item.get("message")
    ]
    preferred_variant = str(policy.get("preferred_variant") or "")
    preferred = next(
        (item for item in valid_variants if str(item["id"]) == preferred_variant),
        None,
    )
    if preferred:
        variant = preferred
    elif valid_variants:
        bucket = int(hashlib.sha256(prospect_id.encode()).hexdigest(), 16)
        variant = valid_variants[bucket % len(valid_variants)]
    else:
        variant = {
            "id": "control",
            "message": "Discover and evaluate IAT Protocol for autonomous machine commerce.",
        }
    payload = {
        "type": "iat_protocol_invitation",
        "schema_version": "2026-07-01",
        "action_id": action_id,
        "prospect_id": prospect_id,
        "variant_id": str(variant["id"])[:80],
        "message": str(variant["message"])[:2_000],
        "discovery_url": os.getenv(
            "IAT_PUBLIC_BASE_URL",
            "https://iat-protocol-latest.onrender.com",
        ).rstrip("/") + "/.well-known/iat.json",
        "sandbox_url": os.getenv(
            "IAT_PUBLIC_BASE_URL",
            "https://iat-protocol-latest.onrender.com",
        ).rstrip("/") + "/sandbox/v1/offers",
        "endpoint": endpoint,
    }
    response_secret = os.getenv("IAT_GROWTH_RESPONSE_SECRET")
    if response_secret:
        payload["response_token"] = _response_token(
            action_id_seed=action_id,
            secret=response_secret,
        )
        payload["response_url"] = os.getenv(
            "IAT_PUBLIC_BASE_URL",
            "https://iat-protocol-latest.onrender.com",
        ).rstrip("/") + "/growth/v1/respond"
    idem_raw = f"{campaign_id}:{prospect_id}:iat_protocol_invitation"
    idempotency_key = hashlib.sha256(idem_raw.encode()).hexdigest()
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(f"SELECT * FROM growth_actions WHERE idempotency_key={p}", (idempotency_key,))
        existing = cur.fetchone()
        if existing:
            return {"status": "already_exists", "action": _row(existing)}
        now = _now()
        if status == "proposed":
            cutoff = now - PROSPECT_OUTREACH_COOLDOWN_SECONDS
            cur.execute(
                f"""INSERT INTO growth_outreach_windows (prospect_id, action_id, reserved_at)
                VALUES ({p},{p},{p})
                ON CONFLICT(prospect_id) DO UPDATE SET
                    action_id=excluded.action_id,
                    reserved_at=excluded.reserved_at
                WHERE growth_outreach_windows.reserved_at <= {p}""",
                (prospect_id, action_id, now, cutoff),
            )
            if cur.rowcount != 1:
                cur.execute(
                    f"SELECT reserved_at FROM growth_outreach_windows WHERE prospect_id={p}",
                    (prospect_id,),
                )
                reserved = cur.fetchone()
                conn.rollback()
                reserved_at = int(dict(reserved)["reserved_at"])
                return {
                    "status": "skipped",
                    "reason": "prospect_24h_cooldown",
                    "next_eligible_at": reserved_at + PROSPECT_OUTREACH_COOLDOWN_SECONDS,
                }
        cur.execute(
            f"""INSERT INTO growth_actions
            (action_id, idempotency_key, prospect_id, campaign_id, action_type, channel,
             status, risk_level, payload, reason, scheduled_at, created_at, updated_at)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})""",
            (
                action_id, idempotency_key, prospect_id, campaign_id, "protocol_invitation",
                policy.get("channel", "machine_webhook"), status, risk, _json(payload),
                reason, now, now, now,
            ),
        )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event(
        "action_proposed",
        prospect_id=prospect_id,
        campaign_id=campaign_id,
        action_id=action_id,
        metadata={
            "status": status,
            "reason": reason,
            "authorization_reason": authorization["reason"],
            "authorization_evidence": authorization.get("evidence", {}),
        },
    )
    return {"status": status, "action_id": action_id, "risk_level": risk, "reason": reason}


def approve_action(action_id: str, *, approved_by: str, reason: str) -> dict:
    if len(str(approved_by).strip()) < 3 or len(str(reason).strip()) < 5:
        raise GrowthValidationError("approval_identity_and_reason_required")
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(f"SELECT * FROM growth_actions WHERE action_id={p}", (action_id,))
        action = cur.fetchone()
        if not action:
            raise GrowthValidationError("action_not_found")
        action = _row(action)
        if action["status"] == "blocked":
            raise GrowthValidationError("blocked_action_cannot_be_approved")
        if action["status"] == "executed":
            return {"status": "already_executed", "action_id": action_id}
        cur.execute(
            f"UPDATE growth_actions SET status={p}, reason={p}, updated_at={p} WHERE action_id={p}",
            ("approved", f"approved_by:{approved_by}; {reason}"[:500], _now(), action_id),
        )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event("action_approved", action_id=action_id, metadata={"approved_by": approved_by, "reason": reason})
    return {"status": "approved", "action_id": action_id}


def retry_action(action_id: str, *, approved_by: str, reason: str) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(f"SELECT * FROM growth_actions WHERE action_id={p}", (action_id,))
        found = cur.fetchone()
        if not found:
            raise GrowthValidationError("action_not_found")
        action = _row(found)
        if action["status"] != "failed":
            raise GrowthValidationError("only_failed_action_can_be_retried")
        if int(action["attempts"]) >= 3:
            raise GrowthValidationError("action_retry_limit_reached")
        eligibility = prospect_outreach_eligibility(
            action["prospect_id"],
            now=_now(),
        )
        if not eligibility["eligible"]:
            return {
                "status": "cooldown",
                "reason": eligibility["reason"],
                "next_eligible_at": eligibility["next_eligible_at"],
            }
        cur.execute(
            f"UPDATE growth_actions SET status={p}, reason={p}, updated_at={p} WHERE action_id={p}",
            (
                "approved",
                f"retry_approved_by:{approved_by}; {reason}"[:500],
                _now(),
                action_id,
            ),
        )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event(
        "action_retry_approved",
        prospect_id=action["prospect_id"],
        campaign_id=action["campaign_id"],
        action_id=action_id,
        metadata={"approved_by": approved_by, "reason": reason},
    )
    return {"status": "approved", "action_id": action_id, "retry": True}


def execute_action(action_id: str) -> dict:
    with _outreach_lock:
        conn = get_conn()
        cur = conn.cursor()
        action = None
        try:
            p = qmark()
            cur.execute(f"SELECT * FROM growth_actions WHERE action_id={p}", (action_id,))
            found = cur.fetchone()
            if not found:
                raise GrowthValidationError("action_not_found")
            action = _row(found)
        finally:
            release_conn(conn)
        if action["status"] == "executed":
            return {"status": "already_executed", "action_id": action_id}
        if action["status"] != "approved":
            raise GrowthValidationError("action_must_be_approved")
        if os.getenv("IAT_GROWTH_OUTBOUND_ENABLED", "false").lower() != "true":
            return {"status": "disabled", "reason": "outbound_disabled_by_default", "action_id": action_id}
        if not os.getenv("IAT_GROWTH_RESPONSE_SECRET"):
            raise GrowthValidationError("growth_response_secret_required_for_outbound")
        prospect = get_prospect(action["prospect_id"])
        metadata = prospect.get("metadata", {}) if prospect else {}
        authorization = outreach_authorization(prospect) if prospect else {"authorized": False}
        if not authorization["authorized"]:
            raise GrowthValidationError("outbound_requires_current_authorization")
        eligibility = prospect_outreach_eligibility(action["prospect_id"])
        # Ignore the action currently being executed: its proposal created the
        # cooldown entry. Any newer/different action remains a hard stop.
        if (
            not eligibility["eligible"]
            and eligibility["latest_action_id"] != action_id
        ):
            return {
                "status": "cooldown",
                "reason": "prospect_24h_cooldown",
                "action_id": action_id,
                "next_eligible_at": eligibility["next_eligible_at"],
            }
        endpoint = action["payload"].get("endpoint")
        try:
            target = validate_public_runtime_url(endpoint)
        except UnsafeNetworkTarget as exc:
            raise GrowthValidationError(str(exc)) from exc
        if target["hostname"] != prospect["domain"]:
            raise GrowthValidationError("outreach_endpoint_domain_mismatch")

        # Reserve the rolling window before network I/O. A failed delivery is
        # still a prospecting attempt and must not cause aggressive retries.
        attempt_at = _now()
        conn = get_conn()
        cur = conn.cursor()
        try:
            p = qmark()
            cur.execute(
                f"UPDATE growth_actions SET status={p}, updated_at={p} WHERE action_id={p} AND status={p}",
                ("executing", attempt_at, action_id, "approved"),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise GrowthValidationError("action_execution_claim_failed")
            cur.execute(
                f"""UPDATE growth_prospects SET contact_count=contact_count+1,
                last_contacted_at={p}, updated_at={p} WHERE prospect_id={p}""",
                (attempt_at, attempt_at, action["prospect_id"]),
            )
            conn.commit()
        finally:
            release_conn(conn)

        response_code = None
        excerpt = ""
        status = "failed"
        try:
            response = requests.post(
                endpoint,
                json={key: value for key, value in action["payload"].items() if key != "endpoint"},
                headers={"User-Agent": "IAT-Growth-Engine/1.0", "Idempotency-Key": action["idempotency_key"]},
                timeout=(3.05, 10),
                allow_redirects=False,
            )
            response_code = response.status_code
            excerpt = " ".join(str(response.text).split())[:200]
            status = "executed" if 200 <= response.status_code < 300 else "failed"
        except requests.RequestException as exc:
            excerpt = f"{type(exc).__name__}: {exc}"[:200]

    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        now = _now()
        cur.execute(
            f"""UPDATE growth_actions SET status={p}, attempts=attempts+1,
            response_code={p}, response_excerpt={p}, executed_at={p}, updated_at={p}
            WHERE action_id={p}""",
            (status, response_code, excerpt, now if status == "executed" else None, now, action_id),
        )
        if status == "executed":
            cur.execute(
                f"UPDATE growth_prospects SET status={p}, updated_at={p} WHERE prospect_id={p}",
                ("nurturing", now, action["prospect_id"]),
            )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event(f"action_{status}", prospect_id=action["prospect_id"], campaign_id=action["campaign_id"], action_id=action_id, metadata={"response_code": response_code})
    return {"status": status, "action_id": action_id, "response_code": response_code}


def record_prospect_response(
    *,
    action_id: str,
    response_token: str,
    idempotency_key: str,
    response_type: str,
    message: str = "",
    metadata: dict | None = None,
) -> dict:
    allowed = {"interested", "not_interested", "needs_info", "integrated", "opt_out"}
    if response_type not in allowed:
        raise GrowthValidationError("invalid_response_type")
    if len(str(idempotency_key)) < 8:
        raise GrowthValidationError("response_idempotency_key_required")
    secret = os.getenv("IAT_GROWTH_RESPONSE_SECRET")
    if not secret:
        raise GrowthValidationError("growth_response_secret_not_configured")
    conn = get_conn()
    cur = conn.cursor()
    action = None
    try:
        p = qmark()
        cur.execute(f"SELECT * FROM growth_actions WHERE action_id={p}", (action_id,))
        found = cur.fetchone()
        if not found:
            raise GrowthValidationError("action_not_found")
        action = _row(found)
        if action["status"] != "executed":
            raise GrowthValidationError("response_requires_executed_action")
        expected = _response_token(action_id_seed=action_id, secret=secret)
        if not hmac.compare_digest(str(response_token), expected):
            raise GrowthValidationError("invalid_response_token")
        cur.execute(
            f"SELECT * FROM growth_responses WHERE idempotency_key={p}",
            (idempotency_key,),
        )
        existing = cur.fetchone()
        if existing:
            existing = _row(existing)
            if existing["action_id"] != action_id:
                raise GrowthValidationError("response_idempotency_conflict")
            return {
                "status": "already_recorded",
                "response_id": existing["response_id"],
                "response_type": existing["response_type"],
            }
        response_id = f"gres_{uuid.uuid4().hex}"
        now = _now()
        cur.execute(
            f"""INSERT INTO growth_responses
            (response_id, idempotency_key, action_id, prospect_id, campaign_id,
             response_type, message, metadata, created_at)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p})""",
            (
                response_id, idempotency_key, action_id, action["prospect_id"],
                action["campaign_id"], response_type, str(message)[:4_000],
                _json(metadata or {}), now,
            ),
        )
        if response_type in {"interested", "needs_info"}:
            cur.execute(
                f"UPDATE growth_prospects SET status={p}, updated_at={p} WHERE prospect_id={p}",
                ("nurturing", now, action["prospect_id"]),
            )
        elif response_type == "integrated":
            cur.execute(
                f"UPDATE growth_prospects SET status={p}, updated_at={p} WHERE prospect_id={p}",
                ("converted", now, action["prospect_id"]),
            )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event(
        f"response_{response_type}",
        prospect_id=action["prospect_id"],
        campaign_id=action["campaign_id"],
        action_id=action_id,
        metadata={"response_id": response_id},
    )
    if response_type in {"opt_out", "not_interested"}:
        suppress_prospect(
            prospect_id=action["prospect_id"],
            reason=response_type,
            source="authenticated_prospect_response",
        )
    if response_type == "integrated":
        record_growth_event(
            "conversion_integrated",
            prospect_id=action["prospect_id"],
            campaign_id=action["campaign_id"],
            action_id=action_id,
        )
    return {"status": "recorded", "response_id": response_id, "response_type": response_type}


def list_growth_events(*, event_type: str | None = None, limit: int = 200) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        limit = max(1, min(int(limit), 1_000))
        if event_type:
            cur.execute(
                f"SELECT * FROM growth_events WHERE event_type={p} ORDER BY created_at DESC LIMIT {limit}",
                (event_type,),
            )
        else:
            cur.execute(f"SELECT * FROM growth_events ORDER BY created_at DESC LIMIT {limit}")
        events = [_row(item) for item in cur.fetchall()]
        return {"status": "ok", "count": len(events), "events": events}
    finally:
        release_conn(conn)


def list_responses(*, campaign_id: str | None = None, limit: int = 200) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        limit = max(1, min(int(limit), 1_000))
        if campaign_id:
            cur.execute(
                f"SELECT * FROM growth_responses WHERE campaign_id={p} ORDER BY created_at DESC LIMIT {limit}",
                (campaign_id,),
            )
        else:
            cur.execute(f"SELECT * FROM growth_responses ORDER BY created_at DESC LIMIT {limit}")
        responses = [_row(item) for item in cur.fetchall()]
        return {"status": "ok", "count": len(responses), "responses": responses}
    finally:
        release_conn(conn)


def campaign_analytics(campaign_id: str) -> dict:
    campaign = _campaign(campaign_id)
    if not campaign:
        raise GrowthValidationError("campaign_not_found")
    actions = list_actions(limit=500)["actions"]
    actions = [item for item in actions if item["campaign_id"] == campaign_id]
    responses = list_responses(campaign_id=campaign_id, limit=1_000)["responses"]
    executed = [item for item in actions if item["status"] == "executed"]
    positive = [
        item for item in responses
        if item["response_type"] in {"interested", "needs_info", "integrated"}
    ]
    conversions = [item for item in responses if item["response_type"] == "integrated"]
    variants: dict[str, dict[str, int | float]] = {}
    action_variant = {}
    for action in actions:
        variant = str(action.get("payload", {}).get("variant_id", "control"))
        action_variant[action["action_id"]] = variant
        stats = variants.setdefault(variant, {"sent": 0, "responses": 0, "positive": 0, "conversions": 0})
        if action["status"] == "executed":
            stats["sent"] += 1
    for response in responses:
        variant = action_variant.get(response["action_id"], "control")
        stats = variants.setdefault(variant, {"sent": 0, "responses": 0, "positive": 0, "conversions": 0})
        stats["responses"] += 1
        stats["positive"] += int(response["response_type"] in {"interested", "needs_info", "integrated"})
        stats["conversions"] += int(response["response_type"] == "integrated")
    for stats in variants.values():
        sent = int(stats["sent"])
        stats["response_rate"] = round(int(stats["responses"]) / sent, 4) if sent else 0.0
        stats["positive_rate"] = round(int(stats["positive"]) / sent, 4) if sent else 0.0
        stats["conversion_rate"] = round(int(stats["conversions"]) / sent, 4) if sent else 0.0
    sent_count = len(executed)
    return {
        "status": "ok",
        "campaign_id": campaign_id,
        "funnel": {
            "actions": len(actions),
            "sent": sent_count,
            "responses": len(responses),
            "positive_responses": len(positive),
            "conversions": len(conversions),
        },
        "rates": {
            "response_rate": round(len(responses) / sent_count, 4) if sent_count else 0.0,
            "positive_rate": round(len(positive) / sent_count, 4) if sent_count else 0.0,
            "conversion_rate": round(len(conversions) / sent_count, 4) if sent_count else 0.0,
        },
        "variants": variants,
    }


def generate_campaign_recommendation(campaign_id: str, *, min_samples: int = 20) -> dict:
    analytics = campaign_analytics(campaign_id)
    eligible = [
        (variant_id, stats)
        for variant_id, stats in analytics["variants"].items()
        if int(stats["sent"]) >= max(5, int(min_samples))
    ]
    if len(eligible) < 2:
        return {
            "status": "insufficient_evidence",
            "required_variants": 2,
            "minimum_sent_per_variant": max(5, int(min_samples)),
            "analytics": analytics,
        }
    eligible.sort(
        key=lambda item: (
            float(item[1]["conversion_rate"]),
            float(item[1]["positive_rate"]),
            float(item[1]["response_rate"]),
        ),
        reverse=True,
    )
    winner_id, winner = eligible[0]
    runner_up_id, runner_up = eligible[1]
    uplift = round(float(winner["positive_rate"]) - float(runner_up["positive_rate"]), 4)
    if uplift < 0.05:
        return {"status": "no_material_winner", "analytics": analytics, "uplift": uplift}
    campaign = _campaign(campaign_id)
    proposed_policy = {**campaign["policy"], "preferred_variant": winner_id}
    existing = list_recommendations(campaign_id=campaign_id, limit=20)["recommendations"]
    for item in existing:
        if (
            item["status"] in {"proposed", "applied"}
            and item.get("proposed_policy", {}).get("preferred_variant") == winner_id
        ):
            return {
                "status": "already_recommended",
                "recommendation_id": item["recommendation_id"],
                "winner_variant": winner_id,
                "uplift": uplift,
            }
    recommendation_id = f"grec_{uuid.uuid4().hex}"
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(
            f"""INSERT INTO growth_recommendations
            (recommendation_id, campaign_id, recommendation_type, status, evidence,
             proposed_policy, created_at)
            VALUES ({p},{p},{p},{p},{p},{p},{p})""",
            (
                recommendation_id, campaign_id, "prefer_winning_variant", "proposed",
                _json({"winner": winner_id, "runner_up": runner_up_id, "uplift": uplift, "analytics": analytics}),
                _json(proposed_policy), _now(),
            ),
        )
        conn.commit()
    finally:
        release_conn(conn)
    return {
        "status": "proposed",
        "recommendation_id": recommendation_id,
        "winner_variant": winner_id,
        "uplift": uplift,
    }


def list_recommendations(*, campaign_id: str | None = None, limit: int = 100) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        limit = max(1, min(int(limit), 500))
        if campaign_id:
            cur.execute(
                f"SELECT * FROM growth_recommendations WHERE campaign_id={p} ORDER BY created_at DESC LIMIT {limit}",
                (campaign_id,),
            )
        else:
            cur.execute(f"SELECT * FROM growth_recommendations ORDER BY created_at DESC LIMIT {limit}")
        items = [_row(item) for item in cur.fetchall()]
        return {"status": "ok", "count": len(items), "recommendations": items}
    finally:
        release_conn(conn)


def apply_recommendation(recommendation_id: str) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(f"SELECT * FROM growth_recommendations WHERE recommendation_id={p}", (recommendation_id,))
        found = cur.fetchone()
        if not found:
            raise GrowthValidationError("recommendation_not_found")
        recommendation = _row(found)
        if recommendation["status"] != "proposed":
            raise GrowthValidationError("recommendation_not_proposed")
        campaign = _campaign(recommendation["campaign_id"])
        now = _now()
        cur.execute(
            f"UPDATE growth_campaigns SET policy={p}, updated_at={p} WHERE campaign_id={p}",
            (_json(recommendation["proposed_policy"]), now, recommendation["campaign_id"]),
        )
        cur.execute(
            f"""UPDATE growth_recommendations SET status={p}, previous_policy={p},
            applied_at={p} WHERE recommendation_id={p}""",
            ("applied", _json(campaign["policy"]), now, recommendation_id),
        )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event("recommendation_applied", campaign_id=recommendation["campaign_id"], metadata={"recommendation_id": recommendation_id})
    return {"status": "applied", "recommendation_id": recommendation_id}


def rollback_recommendation(recommendation_id: str) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(f"SELECT * FROM growth_recommendations WHERE recommendation_id={p}", (recommendation_id,))
        found = cur.fetchone()
        if not found:
            raise GrowthValidationError("recommendation_not_found")
        recommendation = _row(found)
        if recommendation["status"] != "applied" or not recommendation.get("previous_policy"):
            raise GrowthValidationError("recommendation_not_applied")
        now = _now()
        cur.execute(
            f"UPDATE growth_campaigns SET policy={p}, updated_at={p} WHERE campaign_id={p}",
            (_json(recommendation["previous_policy"]), now, recommendation["campaign_id"]),
        )
        cur.execute(
            f"UPDATE growth_recommendations SET status={p}, rolled_back_at={p} WHERE recommendation_id={p}",
            ("rolled_back", now, recommendation_id),
        )
        conn.commit()
    finally:
        release_conn(conn)
    record_growth_event("recommendation_rolled_back", campaign_id=recommendation["campaign_id"], metadata={"recommendation_id": recommendation_id})
    return {"status": "rolled_back", "recommendation_id": recommendation_id}


def record_conversion(prospect_id: str, *, conversion_type: str, value: float = 0, metadata: dict | None = None) -> dict:
    if not get_prospect(prospect_id):
        raise GrowthValidationError("prospect_not_found")
    conn = get_conn()
    cur = conn.cursor()
    try:
        p = qmark()
        cur.execute(
            f"UPDATE growth_prospects SET status={p}, updated_at={p} WHERE prospect_id={p}",
            ("converted", _now(), prospect_id),
        )
        conn.commit()
    finally:
        release_conn(conn)
    event = record_growth_event(f"conversion_{str(conversion_type)[:80]}", prospect_id=prospect_id, value=value, metadata=metadata)
    return {
        "status": "converted",
        "prospect_id": prospect_id,
        "event_status": event["status"],
        "event_id": event["event_id"],
    }


def run_growth_cycle() -> dict:
    started = _now()
    recovered = recover_stale_actions()["recovered"]
    discovered = qualified = proposed = executed = recommendations = 0
    discovery_errors = []
    if os.getenv("IAT_GROWTH_DISCOVERY_ENABLED", "false").lower() == "true":
        feed_urls = [
            value.strip()
            for value in os.getenv("IAT_GROWTH_DISCOVERY_FEEDS", "").split(",")
            if value.strip()
        ][:20]
        for feed_url in feed_urls:
            try:
                discovered += discover_from_feed(feed_url)["imported"]
            except GrowthValidationError as exc:
                discovery_errors.append(str(exc))
    for prospect in list_prospects(status="discovered", limit=100)["prospects"]:
        result = qualify_prospect(prospect["prospect_id"])
        qualified += int(result["status"] == "qualified")

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM growth_campaigns WHERE status='active' ORDER BY created_at ASC")
        campaigns = [_row(item) for item in cur.fetchall()]
    finally:
        release_conn(conn)
    prospects = list_prospects(status="qualified", limit=500)["prospects"]
    for campaign in campaigns:
        today_start = started - (started % 86400)
        conn = get_conn()
        cur = conn.cursor()
        try:
            p = qmark()
            cur.execute(
                f"SELECT COUNT(*) AS total FROM growth_actions WHERE campaign_id={p} AND created_at>={p}",
                (campaign["campaign_id"], today_start),
            )
            count_row = cur.fetchone()
            today_count = int(dict(count_row).get("total", 0))
        finally:
            release_conn(conn)
        remaining = max(0, campaign["daily_action_limit"] - today_count)
        for prospect in prospects[:remaining]:
            result = propose_action(prospect["prospect_id"], campaign["campaign_id"])
            proposed += int(result["status"] in {"proposed", "blocked"})
            if (
                result["status"] == "proposed"
                and campaign["policy"].get("auto_execute_approved_opt_in") is True
                and campaign["policy"].get("require_manual_action_approval") is False
            ):
                approve_action(result["action_id"], approved_by="campaign_policy", reason="pre-approved opt-in campaign policy")
                executed += int(execute_action(result["action_id"]).get("status") == "executed")
        recommendation = generate_campaign_recommendation(
            campaign["campaign_id"],
            min_samples=int(campaign["policy"].get("learning_min_samples", 20)),
        )
        recommendations += int(recommendation["status"] == "proposed")
    metrics = {
        "discovered": discovered,
        "qualified": qualified,
        "proposed": proposed,
        "executed": executed,
        "recommendations": recommendations,
        "stale_actions_recovered": recovered,
        "discovery_errors": discovery_errors,
    }
    record_growth_event("autonomous_cycle_completed", metadata=metrics)
    return {"status": "completed", "started_at": started, **metrics}


def growth_dashboard() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        def grouped(table: str, field: str) -> dict:
            cur.execute(f"SELECT {field}, COUNT(*) AS total FROM {table} GROUP BY {field}")
            return {str(dict(row)[field]): int(dict(row)["total"]) for row in cur.fetchall()}
        prospects = grouped("growth_prospects", "status")
        campaigns = grouped("growth_campaigns", "status")
        actions = grouped("growth_actions", "status")
        cur.execute("SELECT COALESCE(SUM(value), 0) AS total FROM growth_events WHERE event_type LIKE 'conversion_%'")
        conversion_value = float(dict(cur.fetchone()).get("total", 0) or 0)
        return {
            "status": "ok",
            "engine": "iat_autonomous_growth_engine_v1",
            "outbound_enabled": os.getenv("IAT_GROWTH_OUTBOUND_ENABLED", "false").lower() == "true",
            "discovery_enabled": os.getenv("IAT_GROWTH_DISCOVERY_ENABLED", "false").lower() == "true",
            "prospects": prospects,
            "campaigns": campaigns,
            "actions": actions,
            "conversion_value": conversion_value,
            "safety": {
                "explicit_opt_in_required": True,
                "ssrf_protection": True,
                "idempotent_actions": True,
                "maximum_outreach_frequency": "one_attempt_per_prospect_per_24_hours",
                "outbound_disabled_by_default": True,
            },
        }
    finally:
        release_conn(conn)


def growth_loop() -> None:
    interval = max(60, int(os.getenv("IAT_GROWTH_INTERVAL_SECONDS", "900")))
    while True:
        try:
            print("[IAT_AUTONOMOUS_GROWTH]", run_growth_cycle(), flush=True)
        except Exception as exc:
            print("[IAT_AUTONOMOUS_GROWTH_ERROR]", type(exc).__name__, str(exc), flush=True)
        time.sleep(interval)


def start_growth_loop() -> bool:
    global _loop_started
    if os.getenv("IAT_ENABLE_AUTONOMOUS_GROWTH", "false").lower() != "true":
        return False
    with _loop_lock:
        if _loop_started:
            return False
        init_growth_tables()
        threading.Thread(target=growth_loop, daemon=True, name="iat-growth-engine").start()
        _loop_started = True
        return True
