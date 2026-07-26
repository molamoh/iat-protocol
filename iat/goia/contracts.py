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

    @model_validator(mode="after")
    def require_attribution_for_commercial_relationship(self):
        if self.commercial_relationship != "none" and not self.attribution_supported:
            raise ValueError("commercial_relationship_requires_attribution")
        return self


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
