# GOIA merchant pilot

The first production-oriented cohort is deliberately limited to two through
five merchants in France, priced in EUR, for software, API, hosting, or other
digital services.

## Machine onboarding

A merchant publishes a strict provider manifest and a fresh catalog on its own
domain. It can check eligibility without creating an account or triggering any
network action:

```text
POST /goia/v1/pilots/readiness
```

The response is `ready` only when:

- France and EUR are declared;
- at least one `goia_json` or sitemap source is present;
- every catalog is hosted on the merchant's own website domain;
- the complete provider contract is valid.

For a `ready` provider, the authenticated catalog-ingestion route registers the
manifest and its first observations. The collector then refreshes the source
autonomously. A pilot is operational only after all of these checks pass:

1. readiness is `ready`;
2. provider manifest and catalog validation are valid;
3. initial ingestion contains at least one current searchable observation;
4. the collector heartbeat is `healthy`;
5. a real GOIA search returns the offer with its evidence and disclosure.

## Isolation and consent

No partnership message is sent during this pilot. The partnership dispatcher
remains disabled. A merchant that wants machine-to-machine partnership requests
must explicitly opt in using a self-hosted, verified manifest. Commission never
changes organic ranking.

## Render worker configuration

The collector is a separate background worker built from
`Dockerfile.goia-worker`. Required settings:

```text
DATABASE_URL=<same PostgreSQL database as the API>
IAT_GOIA_COLLECTION_ENABLED=true
IAT_GOIA_COLLECTION_HOSTS=merchant-one.example,merchant-two.example
IAT_GOIA_WORKER_INTERVAL_SECONDS=30
IAT_GOIA_WORKER_ID=render-goia-collector-1
IAT_GOIA_PARTNERSHIP_DELIVERY_ENABLED=false
IAT_GOIA_PARTNERSHIP_HTTP_ENABLED=false
```

Its durable status is available to administrators:

```text
GET /admin/goia/workers/health?stale_after_seconds=180
```

A missing heartbeat is not considered healthy. A heartbeat older than the
configured threshold is reported as `stale`.

### Blueprint deployment

`render.goia-worker.yaml` creates only the dedicated collector and does not
manage or modify the existing API service. In Render, create a new Blueprint,
select this repository, and set the Blueprint path to:

```text
render.goia-worker.yaml
```

Render prompts for the two values marked `sync: false`:

- `DATABASE_URL`: the same PostgreSQL connection URL used by the API;
- `IAT_GOIA_COLLECTION_HOSTS`: the exact comma-separated merchant hostnames.

The Blueprint pins the immutable worker image tag for commit `a2441a9`.
Partnership delivery and its HTTP adapter are explicitly disabled. Do not set
either outbound variable to `true` during the merchant pilot.
