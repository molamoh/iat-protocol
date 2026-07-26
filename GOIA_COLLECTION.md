# GOIA controlled collection

GOIA collection is a separate, fail-closed worker for explicitly approved
domains. It is not started by the IAT web API and is disabled by default.

## Safety properties

- exact hostname allowlist;
- HTTPS and public-IP validation;
- connected-peer verification against the resolved public IP set;
- no URL credentials, query strings, fragments, or automatic redirects;
- `robots.txt` required and fail-closed when unavailable or invalid;
- bounded response sizes and timeouts;
- bounded sitemap and JSON-LD extraction;
- XML entities and doctypes rejected;
- no browser or JavaScript execution;
- extracted Web content remains untrusted data;
- every extracted candidate is `review_required`;
- no automatic publication into the GOIA offer index.

## Configuration

```bash
export IAT_GOIA_COLLECTION_ENABLED=false
export IAT_GOIA_COLLECTION_HOSTS=merchant.example
export IAT_GOIA_WORKER_INTERVAL_SECONDS=30
export DATABASE_URL=postgresql://...
```

`IAT_GOIA_COLLECTION_HOSTS` accepts exact comma-separated hostnames. A
subdomain is not implicitly trusted by an allowed parent domain.

## Enqueue

The administrative route requires the Foundation administrator key and an
idempotency key:

```text
POST /admin/goia/collection/jobs
Idempotency-Key: unique-client-key
x-api-key: Foundation administrator credential

{"url":"https://merchant.example/product"}
```

Inspect bounded aggregate status with:

```text
GET /admin/goia/collection/stats
```

## Autonomous review and publication

Collection never publishes an offer directly. Review candidates are available
to the deterministic autonomous review policy. The normal production flow
requires no human operator:

```text
collection
  -> autonomous normalization
  -> deterministic evidence and policy checks
  -> approved and indexed, or quarantined
```

The policy `goia_autonomous_review_v1` requires:

- one supported Schema.org product or service type;
- exactly one structured `Offer`;
- an exact decimal price and ISO currency declared by the provider;
- recognized availability;
- a canonical URL matching the collected provider page;
- an exact URL and SHA-256 evidence binding.

Incomplete, conflicting, unavailable, or unsupported candidates are
quarantined and never published.

Quarantined candidates are retried autonomously with bounded exponential
backoff. After three unsuccessful retries, they move to
`quarantine_exhausted` and remain excluded from search. A failed candidate
never blocks other offers or queries.

Collection jobs use a five-minute worker lease. A job abandoned by a crashed
worker is returned to the queue automatically. After three abandoned
attempts, it fails closed instead of looping forever.

## Autonomous source discovery

The worker reads catalog sources already declared in registered provider
manifests. Supported sitemap sources are seeded once per configured refresh
window with deterministic idempotency keys.

Sitemap jobs have higher queue priority than product pages. Each allowed URL
discovered in a sitemap becomes a parent-bound page job. Expansion is bounded
to 100 page jobs per sitemap execution even if the parsed sitemap contains
more URLs.

```text
provider manifest
  -> due sitemap source
  -> priority sitemap job
  -> bounded same-domain URLs
  -> idempotent page jobs
  -> extraction and autonomous review
```

Non-sitemap source types remain visible as unsupported instead of being
silently treated as pages.

## Native GOIA JSON catalog

A provider can avoid page-by-page extraction by declaring a `goia_json`
catalog source. The public contract validator is:

```text
POST /goia/v1/contracts/catalog/validate
```

Minimal document:

```json
{
  "contract_version": "goia_catalog_v1",
  "provider_id": "gop_example_001",
  "generated_at": 1785020000,
  "expires_at": 1785106400,
  "offers": [
    {
      "offer_id": "translation-api-pro",
      "kind": "api",
      "title": "Translation API Pro",
      "canonical_url": "https://merchant.example/products/api-pro",
      "total_price": "15.00",
      "currency": "EUR",
      "availability": "available"
    }
  ]
}
```

Native catalogs are limited to 500 unique offers and a seven-day lifetime.
The provider, freshness, currency, exact decimal prices, and same-domain offer
URLs are validated. Every generated observation is bound to the exact catalog
URL and SHA-256 document hash.

Administrator-authenticated routes remain available for audit and emergency
override, but are not part of the normal operating path:

```text
GET /admin/goia/review/candidates?status=pending_review
POST /admin/goia/review/candidates/{candidate_id}/approve
POST /admin/goia/review/candidates/{candidate_id}/reject
```

An emergency approval requires a complete, strictly validated
`OfferObservation`, reviewer, and reason. The observation must:

- belong to the provider attached to the collection job;
- contain evidence with the exact collected source URL;
- contain the exact SHA-256 hash of the collected page.

Autonomous and emergency approval are idempotent. Reusing an approved
candidate with a different observation is rejected. Rejection is also
idempotent and never inserts an observation into the public search index.

## Worker

Run separately from the public API:

```bash
python -m iat.goia.collector_worker
```

Or build the dedicated image:

```bash
docker build -f Dockerfile.goia-worker -t goia-collector .
```

The process exits without work when `IAT_GOIA_COLLECTION_ENABLED` is not
exactly `true`.

## Current scope

The first collector supports:

- HTML pages allowed by `robots.txt`;
- Schema.org JSON-LD extraction for `Product`, `SoftwareApplication`, and
  `Service`;
- periodic provider sitemap seeding;
- bounded sitemap expansion into prioritized page jobs.
- native `goia_json` catalogs with autonomous publication.

JavaScript rendering, redirects, unaffiliated public Internet discovery, and
CSV/XML/API catalog adapters are deliberately not enabled.
