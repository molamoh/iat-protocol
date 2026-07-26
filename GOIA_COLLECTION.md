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
- bounded sitemap XML parsing as a library primitive.

Sitemap scheduling, automatic normalization into `OfferObservation`,
JavaScript rendering, redirects, and public Internet discovery are
deliberately not enabled.
