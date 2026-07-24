# Deploy `iat-growth-test-agent` on Render

This is a consenting staging receiver for one-contact IAT acquisition tests.
It must remain separate from the production IAT web service.

## Build and publish

Build the dedicated image from the repository root:

```bash
docker build -f Dockerfile.growth-test-agent \
  -t molamoh/iat-growth-test-agent:latest .
docker push molamoh/iat-growth-test-agent:latest
```

## Create the Render service

1. In Render, select **New > Web Service**.
2. Under **Source Code**, select **Existing Image**.
3. Use `docker.io/molamoh/iat-growth-test-agent:latest`.
4. Name the service `iat-growth-test-agent`.
5. Select a staging/free instance appropriate for a canary.
6. Add the environment variables below before creating the service.

```text
IAT_TEST_AGENT_ALLOWED_IAT_BASE=https://iat-protocol-latest.onrender.com
IAT_TEST_AGENT_RESPONSE_MODE=interested
IAT_TEST_AGENT_HOURLY_LIMIT=10
IAT_TEST_AGENT_DB_PATH=/tmp/iat_growth_test_agent.db
IAT_TEST_AGENT_ADMIN_KEY=<new random secret>
```

Generate the admin secret locally:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Do not reuse the IAT admin key or the Growth response secret.

## Validate

When Render finishes, the public health endpoint must return `200`:

```bash
curl https://iat-growth-test-agent.onrender.com/health
```

Expected shape:

```json
{
  "status": "ok",
  "agent": "iat-growth-test-agent",
  "environment": "staging",
  "response_mode": "interested",
  "callback_enabled": true
}
```

The protected audit endpoint must return `401` without a key:

```bash
curl -i https://iat-growth-test-agent.onrender.com/admin/invitations
```

With the key:

```bash
curl -H "x-api-key: $IAT_TEST_AGENT_ADMIN_KEY" \
  https://iat-growth-test-agent.onrender.com/admin/invitations
```

## Test scenarios

Change `IAT_TEST_AGENT_RESPONSE_MODE` and select **Save and deploy**:

- `interested`: positive reply;
- `needs_info`: asks for the integration contract;
- `integrated`: reports a staging conversion;
- `not_interested`: refusal and Growth suppression;
- `opt_out`: explicit opt-out and Growth suppression.

Each invitation is idempotent. Response tokens are stored only as SHA-256
hashes. The callback URL must be the configured IAT origin and exact
`/growth/v1/respond` path.

For persistent audit history, attach a Render persistent disk at `/var/data`
and set:

```text
IAT_TEST_AGENT_DB_PATH=/var/data/iat_growth_test_agent.db
```
