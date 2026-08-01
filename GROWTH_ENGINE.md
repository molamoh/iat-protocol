# IAT Autonomous Growth Engine

The Growth Engine discovers, qualifies and converts machine-commerce prospects
without allowing uncontrolled outreach.

## Public pilot acquisition

Agents, platforms, marketplaces and sellers can discover and join the current
USDC-to-IAT Solana devnet pilot without waiting for an invitation:

```http
GET /growth/v1/pilot
POST /growth/v1/pilot
```

The application requires an agent URL, a machine-commerce use case and explicit
follow-up consent. Registrations are canonicalized and deduplicated, qualified
immediately, attributed to their acquisition source and exposed in the normal
growth dashboard. Repeated submissions do not inflate pilot conversion metrics.

## Safety model

- External delivery is disabled unless `IAT_GROWTH_OUTBOUND_ENABLED=true`.
- A prospect must either declare `metadata.outreach_opt_in=true` or publish a
  same-domain, timestamped permission in `metadata.outreach_permission`.
- Public permission sources are restricted to `agent_manifest`,
  `machine_registry` and `published_outreach_endpoint`; scraped pages and
  cross-domain claims fail closed.
- `metadata.do_not_contact=true` always wins and permanently blocks proposals.
- Actions are unique per campaign, prospect and action type.
- Redirects are disabled and every endpoint passes public-network SSRF validation.
- Campaign quotas bound daily action volume.
- A global rolling cooldown permits at most one prospecting attempt per agent
  every 24 hours, across every campaign and worker.
- New actions require admin approval by default.
- Every discovery, decision, action and conversion produces an audit event.
- Three consecutive delivery failures open a domain circuit breaker.
- Executions abandoned by a stopped worker are recovered and made visible.

## Runtime configuration

```bash
# Start the autonomous cycle. Disabled by default during initial rollout.
export IAT_ENABLE_AUTONOMOUS_GROWTH=true
export IAT_GROWTH_INTERVAL_SECONDS=900
export IAT_GROWTH_DISCOVERY_ENABLED=true
export IAT_GROWTH_DISCOVERY_FEEDS=https://registry.example/iat-candidates.json
export IAT_GROWTH_DISCOVERY_HOSTS=registry.example

# Enable only after campaigns and opted-in endpoints have been reviewed.
export IAT_GROWTH_OUTBOUND_ENABLED=false
export IAT_PUBLIC_BASE_URL=https://iat-protocol-latest.onrender.com
# Generate with: python -c 'import secrets; print(secrets.token_urlsafe(48))'
export IAT_GROWTH_RESPONSE_SECRET=replace-with-a-long-random-secret
```

The heartbeat qualifies newly discovered prospects, applies campaign filters,
respects daily limits and creates idempotent actions. It can execute only actions
covered by an explicit pre-approved campaign policy and a current, auditable
prospect authorization.

Discovery feeds return either a JSON array or `{"candidates": [...]}`. Each
candidate contains `url`, `name`, `segment` and optional `metadata`. A cycle reads
at most 20 configured feeds, 1 MB per feed and 100 candidates per feed.
See `examples/growth/registry-feed.json` for the registry contract.

A registry may publish authorization as:

```json
{
  "outreach_permission": {
    "allowed": true,
    "source": "agent_manifest",
    "evidence_url": "https://agent.example/.well-known/agent.json",
    "observed_at": 1784915886
  }
}
```

The evidence URL must use HTTPS and belong to the prospect domain.

## Admin workflow

All routes require `x-api-key: $IAT_ADMIN_API_KEY`.

1. `POST /admin/growth/prospects`
2. `POST /admin/growth/prospects/{id}/qualify`
3. `POST /admin/growth/campaigns`
4. `POST /admin/growth/campaigns/{id}/status`
5. `POST /admin/growth/actions/propose`
6. `POST /admin/growth/actions/{id}/approve`
7. `POST /admin/growth/actions/{id}/execute`
8. `POST /admin/growth/prospects/{id}/conversions`

Use `GET /admin/growth/dashboard` for operational metrics and
`POST /admin/growth/cycle` for a controlled manual cycle.

## Operations and learning

- `GET /admin/growth/events`: complete audit trail.
- `GET /admin/growth/responses`: authenticated prospect responses.
- `GET /admin/growth/suppressions`: opt-outs and administrative exclusions.
- `GET /admin/growth/campaigns/{id}/analytics`: funnel and A/B metrics.
- `POST /admin/growth/campaigns/{id}/recommendations`: generate a bounded
  recommendation after enough evidence.
- `POST /admin/growth/recommendations/{id}/apply`: human-approved adaptation.
- `POST /admin/growth/recommendations/{id}/rollback`: restore prior policy.
- `POST /admin/growth/actions/{id}/retry`: retry a failed action after the
  24-hour cooldown, with a maximum of three attempts.

Responses use `/growth/v1/respond`, an HMAC token included in the invitation and
an idempotency key supplied by the responding agent. `opt_out` and
`not_interested` create an immediate global suppression.

## Staging acquisition

Use a webhook or test agent that explicitly opted in. Configure the deployed
service with the response secret and outbound enabled, then run:

```bash
export IAT_GROWTH_SMOKE_BASE_URL=https://your-staging-iat.example
export IAT_GROWTH_SMOKE_PROSPECT_URL=https://your-opted-in-agent.example/iat-invite
export IAT_GROWTH_SMOKE_CONFIRM=true
python scripts/growth_staging_smoke.py
```

The script creates a one-contact campaign, requires an explicit confirmation,
uses the normal admin API and prints the identifiers required to inspect the
response and campaign funnel.

Follow `GROWTH_STAGING_RUNBOOK.md` for Render variables, canary acceptance
criteria, progressive rollout and emergency stop instructions.
