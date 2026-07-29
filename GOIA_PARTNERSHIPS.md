# GOIA autonomous partnership intelligence

GOIA converts privacy-preserving demand signals into ranked commercial
opportunities. This stage does not contact merchants.

## Demand privacy

Every local search records only:

- a SHA-256 fingerprint of normalized query tokens;
- product or service kind;
- country;
- currency;
- day bucket;
- whether the search returned results;
- aggregate result count.

GOIA does not store the raw query, buyer wallet, IP address, session, or buyer
identity in the demand tables.

## Gap scoring

The autonomous opportunity engine aggregates a rolling 30-day market window
and compares it with current, non-sponsored offer coverage.

The score combines:

- unmet-demand ratio;
- bounded demand volume;
- offer scarcity.

Markets scoring at least 60 become `qualified`. Other markets remain
`monitoring`. Refreshing an opportunity is idempotent because its identity is
stable for the combination of kind, country, and currency.

## Operations

The collection worker refreshes opportunities during every maintenance cycle.
Administrative read and refresh routes are available for audit:

```text
GET  /admin/goia/demand/stats
POST /admin/goia/partnership/opportunities/refresh
GET  /admin/goia/partnership/opportunities
```

## Evidence-based merchant prospects

On allowlisted comparison pages, GOIA can extract merchant domains exposed by
Schema.org `Offer.seller.url` or `Offer.url`. The discovered domain is recorded
as untrusted evidence only:

- GOIA does not fetch or resolve the discovered domain;
- malformed, credential-bearing, fragmented, and non-HTTP URLs are rejected;
- repeated independent structured evidence raises a deterministic relevance
  score;
- qualified prospects can be linked to qualified market gaps when their
  Schema.org kind and currency match;
- evidence is bounded and idempotent.

The audit route is:

```text
GET /admin/goia/partnership/prospects
```

All responses explicitly report `outreach_triggered: false`. Prospect rows
also keep `outreach_authorized` and `contact_attempted` false. Permission-aware
outreach remains a separate future stage.

## Explicit partnership permission

Merchant manifests may publish a fail-closed `partnership_discovery` block:

```json
{
  "accepts_partnership_requests": true,
  "request_endpoint": "https://merchant.example/.well-known/goia-partnership",
  "terms_url": "https://merchant.example/partner-terms",
  "relationship_types": ["affiliate"]
}
```

An endpoint and at least one relationship type are mandatory when the opt-in
is true. Partnership URLs must use the provider website domain. A commercial
relationship declared elsewhere in the manifest is not an opt-in.

GOIA reconciles these declarations autonomously and marks a domain-matched
prospect `declared_opt_in`. Removing the block revokes that status on the next
cycle. This declaration is not yet proof that the manifest is self-hosted by
the domain owner, so it never changes `outreach_authorized` and never sends a
request. The administrative refresh route exists for audit and emergency use:

```text
POST /admin/goia/partnership/permissions/refresh
```
