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

Sitemap scheduling, review approval, automatic normalization into
`OfferObservation`, JavaScript rendering, redirects, and public Internet
discovery are deliberately not enabled.
