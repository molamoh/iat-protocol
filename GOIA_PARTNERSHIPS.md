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
  "manifest_url": "https://merchant.example/.well-known/goia-provider.json",
  "request_endpoint": "https://merchant.example/.well-known/goia-partnership",
  "terms_url": "https://merchant.example/partner-terms",
  "relationship_types": ["affiliate"]
}
```

An auto-hosted manifest URL, an endpoint, and at least one relationship type
are mandatory when the opt-in is true. Partnership URLs must use the provider
website domain. A commercial
relationship declared elsewhere in the manifest is not an opt-in.

GOIA reconciles these declarations autonomously and marks a domain-matched
prospect `declared_opt_in`. The controlled worker periodically fetches the
declared manifest through the existing exact-host allowlist and robots policy.
Only an exact normalized manifest hash, provider identity, source URL, and
domain match produce `verified_opt_in`. The verification expires after two
bounded refresh windows.

Removing the block, changing the manifest, or allowing the proof to expire
revokes `outreach_authorized` on the next cycle. Verification only authorizes
the declared endpoint; this stage still sends no request. Administrative
routes exist for audit and emergency use:

```text
POST /admin/goia/partnership/permissions/refresh
GET  /admin/goia/partnership/verifications
```

## Autonomous proposal outbox

Once a qualified market gap is linked to a qualified prospect with a current
`verified_opt_in`, GOIA prepares a strict `goia_partnership_proposal_v1`
document. The proposal contains:

- stable opportunity, prospect, and provider identifiers;
- the merchant-declared request endpoint and relationship type;
- market kind, country, and currency;
- aggregate demand, unmet demand, current coverage, and gap score;
- explicit assertions that no raw query or buyer identity is included;
- a bounded expiry no later than the permission proof.

The identity is deterministic for the opportunity, prospect, and exact
merchant manifest hash. Repeated maintenance cycles therefore cannot create
duplicate proposals. Prepared proposals are cancelled when permission is
revoked and expire automatically.

This phase is preparation only. It performs no HTTP request and the outbox
reports `delivery_enabled: false`:

```text
POST /admin/goia/partnership/proposals/prepare
GET  /admin/goia/partnership/proposals
POST /goia/v1/contracts/partnership-proposal/validate
```

## Fail-closed delivery lifecycle

GOIA now has a separate delivery state machine, independent from collection:

```text
prepared -> delivering -> delivered
                      \-> retryable -> delivering
                      \-> failed
```

Every claim rechecks the current prospect permission, exact merchant manifest
hash, and unexpired self-hosting proof. Claims use short leases so another
worker can recover a task after a crash. Temporary failures use bounded
exponential backoff and stop after three attempts. Permission revocation,
proposal expiry, and manifest changes prevent a new claim.

All transitions are recorded with a deterministic per-proposal event order and
can be audited through:

```text
GET /admin/goia/partnership/delivery/events
```

## Signed HTTP adapter

The optional HTTP adapter sends the canonical proposal JSON with:

- an `Idempotency-Key` equal to the proposal ID;
- SHA-256 content digest;
- timestamp and GOIA Ed25519 public key;
- Ed25519 signature over timestamp, proposal ID, and content digest.

Before sending, it resolves the exact verified endpoint to public addresses.
After connection it checks the actual peer against those addresses, preventing
DNS rebinding. Redirects are never followed. Responses are limited to 64 KiB
and must be JSON matching `goia_partnership_ack_v1` and the exact proposal ID.
Receipts are persisted with the delivery.

The transport requires all three conditions:

```text
IAT_GOIA_PARTNERSHIP_DELIVERY_ENABLED=true
IAT_GOIA_PARTNERSHIP_HTTP_ADAPTER_ENABLED=true
IAT_GOIA_PARTNERSHIP_SIGNING_KEY=<base58 Ed25519 private key>
```

Both enable flags default to false. The public key, never the private key, is
published in `/.well-known/goia.json`. The acknowledgement contract can be
validated without side effects:

```text
POST /goia/v1/contracts/partnership-acknowledgement/validate
```

## Global merchant opt-out

A signed acknowledgement with `status: rejected` and `reason_code: opt_out`
or `do_not_contact` creates a persistent domain suppression. Suppression has
absolute precedence over a self-hosted opt-in, commercial relationship,
qualified demand, and queued proposals.

GOIA immediately sets `outreach_authorized: false`, marks the prospect
`suppressed`, and cancels every remaining proposal for that domain. Permission
refresh cannot remove this state. Suppressions are auditable through:

```text
GET /admin/goia/partnership/suppressions
```

## Autonomous dispatcher service

`Dockerfile.goia-partnership-dispatcher` packages the dispatcher independently
from the collection worker and API. It exits fail-closed unless delivery, the
HTTP adapter, and a valid Ed25519 key are all configured. When active it claims
at most one eligible proposal per cycle and uses the durable recovery policy.

The loop interval is bounded between 5 and 300 seconds:

```text
IAT_GOIA_PARTNERSHIP_DISPATCH_INTERVAL_SECONDS=30
```

## Authenticated merchant decisions

A merchant that wants asynchronous decisions adds its Ed25519 public key to
the self-hosted policy:

```json
{
  "response_signing_public_key": "<merchant Ed25519 public key>"
}
```

The merchant signs the canonical `goia_partnership_response_v1` hash together
with its response ID and timestamp, then submits:

```text
POST /goia/v1/partnership/responses
X-GOIA-Merchant-Signature: <base58 signature>
X-GOIA-Signed-At: <unix timestamp>
```

GOIA accepts `accepted`, `declined`, `needs_info`, and `opt_out` only when:

- the proposal was delivered;
- the provider and proposal match;
- the self-hosted manifest proof is still current;
- the signature matches the manifest key;
- the timestamp is within five minutes;
- accepted terms remain on the merchant domain.

Responses are idempotent. `accepted` produces
`accepted_pending_activation`; it does not activate commission and never
changes organic ranking. `opt_out` immediately invokes global suppression.
Relationships are auditable through:

```text
GET /admin/goia/partnership/relationships
POST /goia/v1/contracts/partnership-response/validate
```
