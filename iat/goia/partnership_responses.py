"""Authenticated merchant decisions for GOIA partnership proposals."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from urllib.parse import urlparse

from solders.pubkey import Pubkey
from solders.signature import Signature

from iat.api.db import get_conn, qmark, release_conn
from iat.goia.contracts import PartnershipResponse


class GOIAPartnershipResponseError(ValueError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _verification_context(proposal_id: str, *, now: int) -> dict[str, Any]:
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT o.proposal_id, o.provider_id, o.prospect_id, o.status,
                   o.manifest_hash AS proposal_manifest_hash,
                   m.website, m.manifest_json, m.manifest_hash,
                   v.manifest_hash AS verified_manifest_hash, v.expires_at,
                   s.domain AS suppressed_domain
            FROM goia_partnership_outbox o
            JOIN goia_merchants m ON m.provider_id = o.provider_id
            JOIN goia_provider_verifications v ON v.provider_id = o.provider_id
            JOIN goia_partner_prospects p ON p.prospect_id = o.prospect_id
            LEFT JOIN goia_partnership_suppressions s ON s.domain = p.domain
            WHERE o.proposal_id = {marker}
            """,
            (proposal_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise GOIAPartnershipResponseError("proposal_not_found")
        context = dict(row)
        if context["status"] != "delivered":
            raise GOIAPartnershipResponseError("proposal_must_be_delivered")
        if (
            context["manifest_hash"] != context["verified_manifest_hash"]
            or context["manifest_hash"] != context["proposal_manifest_hash"]
            or int(context["expires_at"]) <= now
        ):
            raise GOIAPartnershipResponseError("provider_verification_not_current")
        manifest = json.loads(context.pop("manifest_json"))
        policy = manifest.get("partnership_discovery") or {}
        signing_key = str(policy.get("response_signing_public_key") or "")
        if not signing_key:
            raise GOIAPartnershipResponseError("response_signing_key_not_declared")
        context["signing_public_key"] = signing_key
        return context
    finally:
        release_conn(conn)


def record_partner_response(
    response: PartnershipResponse,
    *,
    signature: str,
    signed_at: int,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    if signed_at != response.responded_at or abs(timestamp - signed_at) > 300:
        raise GOIAPartnershipResponseError("response_signature_timestamp_invalid")
    context = _verification_context(response.proposal_id, now=timestamp)
    if response.provider_id != context["provider_id"]:
        raise GOIAPartnershipResponseError("response_provider_mismatch")
    if context.get("suppressed_domain") and response.decision != "opt_out":
        raise GOIAPartnershipResponseError("merchant_suppression_has_precedence")
    payload = response.model_dump(mode="json")
    payload_json = _canonical_json(payload)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
    signing_input = f"{signed_at}\n{response.response_id}\n{payload_hash}".encode()
    try:
        valid_signature = Signature.from_string(signature).verify(
            Pubkey.from_string(context["signing_public_key"]),
            signing_input,
        )
    except ValueError as exc:
        raise GOIAPartnershipResponseError("invalid_response_signature") from exc
    if not valid_signature:
        raise GOIAPartnershipResponseError("invalid_response_signature")
    if response.terms_url is not None:
        terms_host = str(urlparse(str(response.terms_url)).hostname or "").lower()
        website_host = str(urlparse(context["website"]).hostname or "").lower()
        if terms_host != website_host:
            raise GOIAPartnershipResponseError("response_terms_domain_mismatch")

    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT payload_hash, signature FROM goia_partnership_responses
            WHERE response_id = {marker}
            """,
            (response.response_id,),
        )
        existing = cur.fetchone()
        if existing is not None:
            existing = dict(existing)
            if existing["payload_hash"] != payload_hash or existing["signature"] != signature:
                raise GOIAPartnershipResponseError("response_idempotency_conflict")
            return {
                "status": "duplicate",
                "response_id": response.response_id,
                "decision": response.decision,
            }
        cur.execute(
            f"""
            INSERT INTO goia_partnership_responses (
                response_id, proposal_id, provider_id, decision,
                payload_json, payload_hash, signature, signing_public_key,
                received_at, created_at
            ) VALUES ({", ".join([marker] * 10)})
            """,
            (
                response.response_id,
                response.proposal_id,
                response.provider_id,
                response.decision,
                payload_json,
                payload_hash,
                signature,
                context["signing_public_key"],
                timestamp,
                timestamp,
            ),
        )
        relationship_status = {
            "accepted": "accepted_pending_activation",
            "declined": "declined",
            "needs_info": "needs_info",
            "opt_out": "opted_out",
        }[response.decision]
        cur.execute(
            f"""
            INSERT INTO goia_partnership_relationships (
                provider_id, prospect_id, latest_proposal_id,
                latest_response_id, status, terms_url,
                commission_activated, ranking_effect, created_at, updated_at
            ) VALUES ({", ".join([marker] * 10)})
            ON CONFLICT(provider_id, prospect_id) DO UPDATE SET
                latest_proposal_id = {marker}, latest_response_id = {marker},
                status = {marker}, terms_url = {marker},
                commission_activated = 0, ranking_effect = 0, updated_at = {marker}
            """,
            (
                response.provider_id,
                context["prospect_id"],
                response.proposal_id,
                response.response_id,
                relationship_status,
                str(response.terms_url) if response.terms_url else None,
                0,
                0,
                timestamp,
                timestamp,
                response.proposal_id,
                response.response_id,
                relationship_status,
                str(response.terms_url) if response.terms_url else None,
                timestamp,
            ),
        )
        if response.decision == "opt_out":
            domain = str(urlparse(context["website"]).hostname or "").lower().rstrip(".")
            cur.execute(
                f"""
                INSERT INTO goia_partnership_suppressions (
                    domain, provider_id, proposal_id, reason_code,
                    source, created_at, updated_at
                ) VALUES ({", ".join([marker] * 7)})
                ON CONFLICT(domain) DO UPDATE SET
                    provider_id = {marker}, proposal_id = {marker},
                    reason_code = {marker}, source = {marker}, updated_at = {marker}
                """,
                (
                    domain,
                    response.provider_id,
                    response.proposal_id,
                    "opt_out",
                    "signed_partnership_response",
                    timestamp,
                    timestamp,
                    response.provider_id,
                    response.proposal_id,
                    "opt_out",
                    "signed_partnership_response",
                    timestamp,
                ),
            )
            cur.execute(
                f"""
                UPDATE goia_partner_prospects
                SET permission_status = 'suppressed', outreach_authorized = 0,
                    updated_at = {marker}
                WHERE prospect_id = {marker}
                """,
                (timestamp, context["prospect_id"]),
            )
            cur.execute(
                f"""
                UPDATE goia_partnership_outbox
                SET status = 'cancelled', last_error_code = 'merchant_opt_out',
                    updated_at = {marker}
                WHERE prospect_id = {marker}
                  AND status IN ('prepared', 'retryable')
                """,
                (timestamp, context["prospect_id"]),
            )
        conn.commit()
        return {
            "status": "recorded",
            "response_id": response.response_id,
            "decision": response.decision,
            "relationship_status": relationship_status,
            "commission_activated": False,
            "ranking_effect": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def list_partner_relationships(*, limit: int = 100) -> dict[str, Any]:
    marker = qmark()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT * FROM goia_partnership_relationships
            ORDER BY updated_at DESC, provider_id ASC
            LIMIT {marker}
            """,
            (max(1, min(int(limit), 500)),),
        )
        items = list(map(dict, cur.fetchall()))
        return {"status": "ok", "count": len(items), "items": items}
    finally:
        release_conn(conn)
