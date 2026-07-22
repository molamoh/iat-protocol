"""
Central authority evaluation for IAT Protocol.

SECURITY EVOLUTION DOCTRINE
===========================

Every evolution introduced in this module must reinforce:

- AUTONOMY:
  IAT must enforce identity and security policy automatically.

- INTELLIGENCE:
  decisions must expose structured reasons and policy metadata so that
  governance, scoring, anomaly detection and adaptive defense can consume them.

- SCALABILITY:
  policies must be centralized and reusable instead of being duplicated
  inside individual API routes.

V1 keeps backward compatibility by using IAT_ADMIN_API_KEY as the trusted
Foundation bootstrap credential.

The authorization boundary is nevertheless independent, allowing a future
migration to signed Foundation identities, rotating credentials or service
certificates without modifying runtime routes.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import HTTPException


FOUNDATION_AUTHORITY_POLICY_VERSION = "foundation_authority_v1"


@dataclass(frozen=True)
class AccessDecision:
    """
    Structured authorization decision.

    This object is intentionally machine-readable so that future IAT
    governance, security memory and adaptive policy engines can consume it.
    """

    allowed: bool
    authority: str
    reason: str
    policy_version: str
    fail_closed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_credential(value: str | None) -> str:
    return str(value or "").strip()


def evaluate_foundation_authority(
    presented_credential: str | None,
) -> AccessDecision:
    """
    Evaluate whether the caller holds Foundation bootstrap authority.

    Security properties:
    - fail-closed when the server credential is absent;
    - fail-closed when the caller credential is absent;
    - constant-time credential comparison;
    - structured and auditable decision result.
    """

    expected_credential = _normalize_credential(
        os.getenv("IAT_ADMIN_API_KEY")
    )
    presented = _normalize_credential(presented_credential)

    if not expected_credential:
        return AccessDecision(
            allowed=False,
            authority="foundation",
            reason="foundation_authority_not_configured",
            policy_version=FOUNDATION_AUTHORITY_POLICY_VERSION,
        )

    if not presented:
        return AccessDecision(
            allowed=False,
            authority="foundation",
            reason="foundation_credential_missing",
            policy_version=FOUNDATION_AUTHORITY_POLICY_VERSION,
        )

    if not secrets.compare_digest(presented, expected_credential):
        return AccessDecision(
            allowed=False,
            authority="foundation",
            reason="foundation_credential_invalid",
            policy_version=FOUNDATION_AUTHORITY_POLICY_VERSION,
        )

    return AccessDecision(
        allowed=True,
        authority="foundation",
        reason="foundation_authority_verified",
        policy_version=FOUNDATION_AUTHORITY_POLICY_VERSION,
    )


def enforce_foundation_authority(
    presented_credential: str | None,
    *,
    decision: AccessDecision | None = None,
) -> AccessDecision:
    """
    Enforce Foundation authority and return the structured decision.

    The public HTTP error remains deliberately generic to avoid exposing
    credential configuration or validation details to an attacker.
    """

    decision = decision or evaluate_foundation_authority(
        presented_credential
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=401,
            detail="unauthorized_foundation_agent_identity",
        )

    return decision
