"""Strict, side-effect-free contracts for GOIA commercial discovery."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)


GOIA_CONTRACT_VERSION = "goia_contracts_v1"

MoneyString = Annotated[
    str,
    StringConstraints(pattern=r"^(0|[1-9]\d{0,11})(\.\d{1,8})?$"),
]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
LanguageCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class StrictGOIAModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Requirement(StrictGOIAModel):
    attribute: str = Field(min_length=1, max_length=80)
    operator: Literal["eq", "neq", "gte", "lte", "contains", "in"]
    value: str | int | bool = Field()
    unit: str | None = Field(default=None, max_length=32)


class SearchIntent(StrictGOIAModel):
    contract_version: Literal["goia_contracts_v1"] = GOIA_CONTRACT_VERSION
    query: str = Field(min_length=3, max_length=2_000)
    kind: Literal["software", "api", "hosting", "digital_service"]
    country: CountryCode = "FR"
    currency: CurrencyCode = "EUR"
    language: LanguageCode = "fr-FR"
    maximum_total_price: MoneyString | None = None
    required: list[Requirement] = Field(default_factory=list, max_length=50)
    preferred: list[Requirement] = Field(default_factory=list, max_length=50)
    strategy: Literal["balanced", "cheapest", "fastest", "safest", "quality"] = "balanced"
    result_limit: int = Field(default=10, ge=1, le=50)
    realtime_verification: bool = False


class EvidenceReference(StrictGOIAModel):
    source_url: HttpUrl
    extraction_method: Literal[
        "partner_catalog",
        "json_ld",
        "microdata",
        "sitemap",
        "html_rule",
        "manual_verification",
    ]
    content_sha256: Sha256Hex
    observed_at: int = Field(gt=0)


class OfferObservation(StrictGOIAModel):
    contract_version: Literal["goia_contracts_v1"] = GOIA_CONTRACT_VERSION
    observation_id: str = Field(pattern=r"^goo_[a-zA-Z0-9_-]{12,100}$")
    offer_id: str = Field(min_length=3, max_length=160)
    merchant_id: str = Field(min_length=3, max_length=160)
    kind: Literal["software", "api", "hosting", "digital_service"]
    title: str = Field(min_length=3, max_length=500)
    canonical_url: HttpUrl
    total_price: MoneyString
    currency: CurrencyCode
    availability: Literal[
        "available",
        "unavailable",
        "limited",
        "unknown",
    ]
    observed_at: int = Field(gt=0)
    expires_at: int = Field(gt=0)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=20)
    attribute_confidence: int = Field(ge=0, le=100)
    commercial_relationship: Literal[
        "none",
        "affiliate",
        "direct_partner",
        "sponsored",
    ] = "none"
    sponsored: bool = False

    @model_validator(mode="after")
    def validate_timing_and_disclosure(self):
        if self.expires_at <= self.observed_at:
            raise ValueError("expires_at_must_follow_observed_at")
        if self.sponsored != (self.commercial_relationship == "sponsored"):
            raise ValueError("sponsored_disclosure_must_match_relationship")
        if any(item.observed_at > self.observed_at for item in self.evidence):
            raise ValueError("evidence_cannot_be_newer_than_observation")
        return self


class CatalogSource(StrictGOIAModel):
    source_id: str = Field(min_length=3, max_length=120)
    source_type: Literal["goia_json", "json", "csv", "xml", "api", "sitemap"]
    url: HttpUrl
    refresh_interval_seconds: int = Field(ge=300, le=2_592_000)


class PartnershipDiscoveryPolicy(StrictGOIAModel):
    accepts_partnership_requests: bool = False
    manifest_url: HttpUrl | None = None
    request_endpoint: HttpUrl | None = None
    terms_url: HttpUrl | None = None
    response_signing_public_key: str | None = Field(
        default=None,
        pattern=r"^[1-9A-HJ-NP-Za-km-z]{32,44}$",
    )
    verification_interval_seconds: int = Field(default=86_400, ge=3_600, le=604_800)
    relationship_types: list[Literal["affiliate", "direct_partner"]] = Field(
        default_factory=list,
        max_length=2,
    )

    @model_validator(mode="after")
    def validate_explicit_opt_in(self):
        if self.accepts_partnership_requests:
            if (
                self.manifest_url is None
                or self.request_endpoint is None
                or not self.relationship_types
            ):
                raise ValueError(
                    "partnership_opt_in_requires_manifest_endpoint_and_relationship"
                )
        elif self.manifest_url is not None or self.request_endpoint is not None or self.relationship_types:
            raise ValueError("partnership_details_require_explicit_opt_in")
        return self


class MerchantProviderManifest(StrictGOIAModel):
    contract_version: Literal["goia_contracts_v1"] = GOIA_CONTRACT_VERSION
    provider_id: str = Field(pattern=r"^gop_[a-zA-Z0-9_-]{8,100}$")
    name: str = Field(min_length=2, max_length=160)
    website: HttpUrl
    countries: list[CountryCode] = Field(min_length=1, max_length=100)
    currencies: list[CurrencyCode] = Field(min_length=1, max_length=20)
    catalogs: list[CatalogSource] = Field(min_length=1, max_length=20)
    commercial_relationship: Literal[
        "none",
        "affiliate",
        "direct_partner",
    ] = "none"
    attribution_supported: bool = False
    partnership_discovery: PartnershipDiscoveryPolicy = Field(
        default_factory=PartnershipDiscoveryPolicy
    )

    @model_validator(mode="after")
    def require_attribution_for_commercial_relationship(self):
        if self.commercial_relationship != "none" and not self.attribution_supported:
            raise ValueError("commercial_relationship_requires_attribution")
        website_host = str(self.website.host or "").lower().rstrip(".")
        policy = self.partnership_discovery
        for endpoint in (policy.manifest_url, policy.request_endpoint, policy.terms_url):
            if endpoint is not None and str(endpoint.host or "").lower().rstrip(".") != website_host:
                raise ValueError("partnership_urls_must_match_provider_domain")
        return self


def evaluate_pilot_readiness(manifest: MerchantProviderManifest) -> dict:
    """Evaluate a provider without registering it or performing network access."""
    website_host = str(manifest.website.host or "").lower().rstrip(".")
    catalog_hosts = {
        str(source.url.host or "").lower().rstrip(".")
        for source in manifest.catalogs
    }
    source_types = {source.source_type for source in manifest.catalogs}
    blockers: list[str] = []
    warnings: list[str] = []

    if "FR" not in manifest.countries:
        blockers.append("pilot_requires_france")
    if "EUR" not in manifest.currencies:
        blockers.append("pilot_requires_eur")
    if any(host != website_host for host in catalog_hosts):
        blockers.append("catalogs_must_be_self_hosted")
    if not source_types.intersection({"goia_json", "sitemap"}):
        blockers.append("pilot_requires_supported_catalog_source")
    if "goia_json" not in source_types:
        warnings.append("native_goia_json_catalog_recommended")
    if manifest.commercial_relationship != "none" and not (
        manifest.partnership_discovery.accepts_partnership_requests
    ):
        warnings.append("commercial_relationship_has_no_machine_partnership_endpoint")

    return {
        "status": "ready" if not blockers else "not_ready",
        "provider_id": manifest.provider_id,
        "pilot_scope": {
            "country": "FR",
            "currency": "EUR",
            "supported_kinds": [
                "software",
                "api",
                "hosting",
                "digital_service",
            ],
        },
        "blockers": blockers,
        "warnings": warnings,
        "next_action": (
            "submit_to_authenticated_catalog_ingest"
            if not blockers
            else "correct_manifest_and_revalidate"
        ),
        "registration_performed": False,
        "network_access_performed": False,
    }


class NativeCatalogOffer(StrictGOIAModel):
    offer_id: str = Field(min_length=3, max_length=160)
    kind: Literal["software", "api", "hosting", "digital_service"]
    title: str = Field(min_length=3, max_length=500)
    canonical_url: HttpUrl
    total_price: MoneyString
    currency: CurrencyCode
    availability: Literal["available", "limited", "unavailable"]


class NativeCatalogDocument(StrictGOIAModel):
    contract_version: Literal["goia_catalog_v1"] = "goia_catalog_v1"
    provider_id: str = Field(pattern=r"^gop_[a-zA-Z0-9_-]{8,100}$")
    generated_at: int = Field(gt=0)
    expires_at: int = Field(gt=0)
    offers: list[NativeCatalogOffer] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_catalog_lifetime(self):
        if self.expires_at <= self.generated_at:
            raise ValueError("catalog_expires_at_must_follow_generated_at")
        if self.expires_at - self.generated_at > 604_800:
            raise ValueError("catalog_lifetime_exceeds_seven_days")
        offer_ids = [item.offer_id for item in self.offers]
        if len(offer_ids) != len(set(offer_ids)):
            raise ValueError("duplicate_catalog_offer_id")
        return self


class PartnershipProposal(StrictGOIAModel):
    contract_version: Literal["goia_partnership_proposal_v1"] = (
        "goia_partnership_proposal_v1"
    )
    proposal_id: str = Field(pattern=r"^gpr_[a-f0-9]{32}$")
    opportunity_id: str = Field(pattern=r"^gpo_[a-f0-9]{32}$")
    prospect_id: str = Field(pattern=r"^gpp_[a-f0-9]{32}$")
    provider_id: str = Field(pattern=r"^gop_[a-zA-Z0-9_-]{8,100}$")
    request_endpoint: HttpUrl
    relationship_type: Literal["affiliate", "direct_partner"]
    market: dict[Literal["kind", "country", "currency"], str]
    aggregate_evidence: dict[
        Literal["demand_count", "unmet_count", "current_offer_count", "gap_score"],
        int,
    ]
    created_at: int = Field(gt=0)
    expires_at: int = Field(gt=0)
    raw_queries_included: Literal[False] = False
    buyer_identity_included: Literal[False] = False

    @model_validator(mode="after")
    def validate_proposal_lifetime(self):
        if self.expires_at <= self.created_at:
            raise ValueError("proposal_expires_at_must_follow_created_at")
        if self.expires_at - self.created_at > 604_800:
            raise ValueError("proposal_lifetime_exceeds_seven_days")
        return self


class PartnershipAcknowledgement(StrictGOIAModel):
    contract_version: Literal["goia_partnership_ack_v1"] = "goia_partnership_ack_v1"
    proposal_id: str = Field(pattern=r"^gpr_[a-f0-9]{32}$")
    status: Literal["received", "duplicate", "rejected"]
    received_at: int = Field(gt=0)
    reason_code: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{2,79}$",
    )

    @model_validator(mode="after")
    def require_rejection_reason(self):
        if self.status == "rejected" and self.reason_code is None:
            raise ValueError("rejected_acknowledgement_requires_reason")
        return self


class PartnershipResponse(StrictGOIAModel):
    contract_version: Literal["goia_partnership_response_v1"] = (
        "goia_partnership_response_v1"
    )
    response_id: str = Field(pattern=r"^gprs_[a-f0-9]{32}$")
    proposal_id: str = Field(pattern=r"^gpr_[a-f0-9]{32}$")
    provider_id: str = Field(pattern=r"^gop_[a-zA-Z0-9_-]{8,100}$")
    decision: Literal["accepted", "declined", "needs_info", "opt_out"]
    responded_at: int = Field(gt=0)
    terms_url: HttpUrl | None = None
    reason_code: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{2,79}$",
    )

    @model_validator(mode="after")
    def validate_decision_details(self):
        if self.decision == "accepted" and self.terms_url is None:
            raise ValueError("accepted_response_requires_terms_url")
        if self.decision in {"declined", "needs_info", "opt_out"} and self.reason_code is None:
            raise ValueError("non_acceptance_response_requires_reason")
        return self
