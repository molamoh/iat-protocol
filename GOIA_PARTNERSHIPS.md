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

All responses explicitly report `outreach_triggered: false`. Merchant
discovery and permission-aware outreach are separate future stages.
