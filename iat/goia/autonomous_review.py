"""Autonomous, deterministic GOIA candidate review."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from iat.goia.contracts import OfferObservation
from iat.goia.repository import (
    approve_review_candidate,
    get_review_candidate,
    quarantine_review_candidate,
)


AUTONOMOUS_REVIEW_POLICY = "goia_autonomous_review_v1"
_MONEY = re.compile(r"^(0|[1-9]\d{0,11})(\.\d{1,8})?$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_AVAILABILITY = {
    "https://schema.org/InStock": "available",
    "http://schema.org/InStock": "available",
    "InStock": "available",
    "https://schema.org/LimitedAvailability": "limited",
    "http://schema.org/LimitedAvailability": "limited",
    "LimitedAvailability": "limited",
    "https://schema.org/OutOfStock": "unavailable",
    "http://schema.org/OutOfStock": "unavailable",
    "OutOfStock": "unavailable",
}


class GOIAAutonomousReviewError(ValueError):
    pass


def _single_offer(candidate: dict) -> dict:
    offers = candidate.get("offers")
    if isinstance(offers, list):
        if len(offers) != 1:
            raise GOIAAutonomousReviewError("exactly_one_offer_required")
        offers = offers[0]
    if not isinstance(offers, dict):
        raise GOIAAutonomousReviewError("structured_offer_required")
    offer_type = offers.get("@type")
    types = {offer_type} if isinstance(offer_type, str) else set(offer_type or [])
    if "Offer" not in types:
        raise GOIAAutonomousReviewError("schema_offer_type_required")
    return offers


def _kind(types: list[str]) -> str:
    if "SoftwareApplication" in types:
        return "software"
    if "Service" in types:
        return "digital_service"
    raise GOIAAutonomousReviewError("unsupported_schema_type")


def normalize_candidate(candidate_record: dict) -> OfferObservation:
    raw = candidate_record["raw"]
    manifest = candidate_record["provider_manifest"]
    source_url = candidate_record["source_url"]
    canonical_url = str(raw.get("url") or "")
    extraction_method = str(raw.get("extraction_method") or "json_ld")
    if extraction_method not in {"json_ld", "partner_catalog"}:
        raise GOIAAutonomousReviewError("unsupported_extraction_method")
    if extraction_method == "json_ld" and canonical_url != source_url:
        raise GOIAAutonomousReviewError("canonical_url_must_match_collected_source")
    if (
        extraction_method == "partner_catalog"
        and urlparse(canonical_url).hostname != urlparse(source_url).hostname
    ):
        raise GOIAAutonomousReviewError("catalog_offer_source_domain_mismatch")
    if urlparse(canonical_url).hostname != urlparse(str(manifest["website"])).hostname:
        raise GOIAAutonomousReviewError("canonical_url_provider_domain_mismatch")
    name = str(raw.get("name") or "").strip()
    if len(name) < 3:
        raise GOIAAutonomousReviewError("candidate_name_required")
    offer = _single_offer(raw)
    price = str(offer.get("price") or "").strip()
    currency = str(offer.get("priceCurrency") or "").strip().upper()
    if not _MONEY.fullmatch(price):
        raise GOIAAutonomousReviewError("exact_decimal_price_required")
    if not _CURRENCY.fullmatch(currency):
        raise GOIAAutonomousReviewError("iso_currency_required")
    if currency not in set(manifest.get("currencies") or []):
        raise GOIAAutonomousReviewError("currency_not_declared_by_provider")
    availability_raw = str(offer.get("availability") or "")
    availability = _AVAILABILITY.get(availability_raw)
    if availability is None:
        raise GOIAAutonomousReviewError("recognized_availability_required")
    if availability == "unavailable":
        raise GOIAAutonomousReviewError("unavailable_offer_not_published")

    stable = hashlib.sha256(
        (
            f"{candidate_record['candidate_id']}:{candidate_record['source_sha256']}:"
            f"{price}:{currency}:{availability}"
        ).encode()
    ).hexdigest()
    observed_at = int(candidate_record["created_at"])
    catalog_expiry = int(raw.get("catalog_expires_at") or observed_at + 3_600)
    expires_at = min(observed_at + 604_800, catalog_expiry)
    if expires_at <= observed_at:
        raise GOIAAutonomousReviewError("candidate_expired_before_review")
    relationship = str(manifest.get("commercial_relationship") or "none")
    declared_kind = raw.get("goia_kind")
    normalized_kind = (
        str(declared_kind)
        if declared_kind in {"software", "api", "hosting", "digital_service"}
        else _kind(list(raw.get("schema_types") or []))
    )
    declared_offer_id = str(raw.get("goia_offer_id") or "").strip()
    normalized_offer_id = declared_offer_id or f"offer_{stable[32:64]}"
    return OfferObservation(
        observation_id=f"goo_{stable[:32]}",
        offer_id=normalized_offer_id,
        merchant_id=candidate_record["provider_id"],
        kind=normalized_kind,
        title=name,
        canonical_url=canonical_url,
        total_price=price,
        currency=currency,
        availability=availability,
        observed_at=observed_at,
        expires_at=expires_at,
        evidence=[
            {
                "source_url": source_url,
                "extraction_method": extraction_method,
                "content_sha256": candidate_record["source_sha256"],
                "observed_at": observed_at,
            }
        ],
        attribute_confidence=95,
        commercial_relationship=relationship,
        sponsored=False,
    )


def autonomously_review_candidate(candidate_id: str) -> dict:
    candidate = get_review_candidate(candidate_id)
    if candidate["status"] == "approved":
        return {
            "candidate_id": candidate_id,
            "status": "approved",
            "state": "already_approved",
            "policy": AUTONOMOUS_REVIEW_POLICY,
        }
    if candidate["status"] == "quarantined":
        return {
            "candidate_id": candidate_id,
            "status": "quarantined",
            "state": "already_quarantined",
            "policy": AUTONOMOUS_REVIEW_POLICY,
            "reason": candidate["reason"],
        }
    try:
        observation = normalize_candidate(candidate)
    except GOIAAutonomousReviewError as exc:
        result = quarantine_review_candidate(
            candidate_id,
            policy=AUTONOMOUS_REVIEW_POLICY,
            reason=str(exc),
        )
        return {**result, "policy": AUTONOMOUS_REVIEW_POLICY}
    result = approve_review_candidate(
        candidate_id,
        observation=observation,
        reviewer=AUTONOMOUS_REVIEW_POLICY,
        reason="deterministic_policy_and_exact_evidence_passed",
    )
    return {**result, "policy": AUTONOMOUS_REVIEW_POLICY}
