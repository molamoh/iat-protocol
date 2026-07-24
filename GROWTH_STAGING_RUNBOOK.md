# IAT Growth Engine — Staging Runbook

This runbook is for an explicitly opted-in staging agent. It must not be used
to contact an unrelated production service.

## 1. Required external test target

The target must expose an HTTPS endpoint accepting:

```http
POST /iat-invite
Content-Type: application/json
Idempotency-Key: <stable IAT action key>
User-Agent: IAT-Growth-Engine/1.0
```

It should return `200`, `201`, `202` or `204` and store the invitation body.
The body contains `action_id`, `response_url` and `response_token`. The target
can answer by sending:

```json
{
  "action_id": "gact_...",
  "response_token": "...",
  "idempotency_key": "target-generated-unique-key",
  "response_type": "interested",
  "message": "Send the sandbox integration contract.",
  "metadata": {
    "agent_version": "staging-1"
  }
}
```

to the supplied `response_url`.

## 2. Render staging variables

Generate secrets locally and enter them directly in Render. Do not paste them
into source control.

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Configure:

```text
IAT_ADMIN_API_KEY=<existing strong admin key>
IAT_GROWTH_RESPONSE_SECRET=<new generated secret>
IAT_PUBLIC_BASE_URL=https://iat-protocol-latest.onrender.com
IAT_ENABLE_AUTONOMOUS_GROWTH=false
IAT_GROWTH_DISCOVERY_ENABLED=false
IAT_GROWTH_OUTBOUND_ENABLED=true
IAT_GROWTH_INTERVAL_SECONDS=900
```

The first test remains manual even though outbound is enabled.

## 3. One-contact canary

On the operator machine:

```bash
export IAT_ADMIN_API_KEY='<same Render admin key>'
export IAT_GROWTH_SMOKE_BASE_URL='https://iat-protocol-latest.onrender.com'
export IAT_GROWTH_SMOKE_PROSPECT_URL='https://OPTED-IN-TARGET/iat-invite'
export IAT_GROWTH_SMOKE_CONFIRM=true
python scripts/growth_staging_smoke.py
```

Expected execution status: `executed` with HTTP `2xx`.

## 4. Verification

Use the IDs printed by the script:

```bash
curl -H "x-api-key: $IAT_ADMIN_API_KEY" \
  "$IAT_GROWTH_SMOKE_BASE_URL/admin/growth/actions"

curl -H "x-api-key: $IAT_ADMIN_API_KEY" \
  "$IAT_GROWTH_SMOKE_BASE_URL/admin/growth/responses"

curl -H "x-api-key: $IAT_ADMIN_API_KEY" \
  "$IAT_GROWTH_SMOKE_BASE_URL/admin/growth/campaigns/CAMPAIGN_ID/analytics"

curl -H "x-api-key: $IAT_ADMIN_API_KEY" \
  "$IAT_GROWTH_SMOKE_BASE_URL/admin/growth/events"
```

Pass criteria:

- exactly one executed action;
- the same prospect cannot receive another proposal for 24 hours;
- the response appears once even if resent with the same idempotency key;
- an `opt_out` creates a suppression immediately;
- no unapproved action is executed;
- no secret appears in logs or response excerpts.

## 5. Progressive rollout

1. One manually approved opted-in agent.
2. Five opted-in agents, daily limit `5`, manual approval.
3. Twenty opted-in agents, daily limit `20`, two message variants.
4. Generate a recommendation only after at least 20 sends per variant.
5. Apply a recommendation manually and monitor it for 48 hours.
6. Enable the autonomous loop only after every preceding gate passes.

Keep `require_opt_in=true` at every stage.

## 6. Immediate stop conditions

Set these variables and redeploy:

```text
IAT_GROWTH_OUTBOUND_ENABLED=false
IAT_ENABLE_AUTONOMOUS_GROWTH=false
```

Stop immediately if:

- any non-opted-in endpoint receives a message;
- duplicate outreach occurs inside 24 hours;
- a suppression is ignored;
- three consecutive deliveries fail for a domain;
- response authentication fails unexpectedly;
- action volume exceeds the campaign daily limit.
