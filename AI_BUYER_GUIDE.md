# IAT Buyer Interface

This guide describes the stable, machine-oriented entry points for an AI buyer.
The sandbox is intentionally isolated from production execution and settlement.

## Discover the protocol

```bash
curl http://localhost:8000/.well-known/iat.json
curl http://localhost:8000/v1/capabilities
curl http://localhost:8000/openapi-public.json
curl http://localhost:8000/llms.txt
```

`/.well-known/iat.json` is the canonical navigation document. Clients should
discover endpoint paths from this document instead of hardcoding deployment
hosts.

## Evaluate IAT without funds

List available simulations:

```bash
curl "http://localhost:8000/sandbox/v1/offers?service=web_research"
```

Preview a policy-compliant selection:

```bash
curl -X POST http://localhost:8000/sandbox/v1/preview \
  -H "Content-Type: application/json" \
  -d '{
    "service": "web_research",
    "goal": "Compare autonomous agent payment protocols",
    "max_price": "2.00",
    "strategy": "quality",
    "required_capabilities": ["source_verification"]
  }'
```

Run the simulation:

```bash
curl -X POST http://localhost:8000/sandbox/v1/purchase \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: buyer-evaluation-0001" \
  -d '{
    "service": "web_research",
    "goal": "Compare autonomous agent payment protocols",
    "max_price": "2.00",
    "strategy": "quality",
    "required_capabilities": ["source_verification"]
  }'
```

Repeating the exact request with the same idempotency key returns the existing
order. Reusing the key with a different request returns HTTP `409`.

## Python buyer

```python
from iat import IATClient

client = IATClient("http://localhost:8000")

order = client.sandbox_buy(
    "web_research",
    goal="Compare autonomous agent payment protocols",
    max_price="2.00",
    strategy="quality",
    required_capabilities=["source_verification"],
    idempotency_key="buyer-evaluation-0001",
)

assert order["funds_moved"] is False
print(order["selection_explanation"])
print(order["result"])
```

The complete executable example is
[`examples/sdk/ai_buyer_quickstart.py`](examples/sdk/ai_buyer_quickstart.py).

## Error contract

The Python client raises:

- `IATTransportError` when a server cannot be reached after bounded retries;
- `IATAPIError` when the server rejects a request;
- `IATClientError` as the common base type.

Each error exposes `as_dict()` for machine-oriented recovery logic. Production
POST requests are not retried automatically. An idempotent sandbox purchase can
be retried because it carries an explicit idempotency key.

## Safety model

The sandbox guarantees:

- no wallet access;
- no token transfer;
- no production supplier call;
- strict budget and capability constraints;
- deterministic, explainable ranking;
- bounded in-memory reputation adaptation;
- no policy mutation and no self-modifying code;
- sandbox receipts that are explicitly invalid as settlement proofs.

Feedback changes only a sandbox offer adjustment between `-5` and `+5`.
Feedback is idempotent and has no effect on production trust or settlement.

## Bounded autonomous purchase policy

A wallet-authenticated buyer can persist an explicit fail-closed policy before
asking an agent to prepare autonomous purchases:

```http
PUT /payments/v1/universal/buyer/purchase-policy
Authorization: Bearer ias_...
Content-Type: application/json

{
  "enabled": true,
  "input_asset": "USDC",
  "max_per_order_minor": 2000000,
  "daily_limit_minor": 5000000,
  "allowed_services": ["web_research"]
}
```

Amounts use the input asset's atomic unit. For USDC, `2000000` represents 2
USDC. The policy can be inspected with `GET` on the same route.

The wallet checkout request accepts `"autonomous": true`. In that mode IAT
refuses preparation unless the policy is enabled and the asset, service,
per-order amount and cumulative UTC-day amount are all permitted. Quote
reservations are idempotent; expired unpaid quotes release their reservation,
while submitted or confirmed payments remain in the daily total.

This policy authorizes only bounded checkout preparation. It does not transfer
funds or grant custody to IAT. On-chain delegated execution is a later phase
and will require a separate cryptographic authorization contract.

## Authenticated marketplace intent preview

An authenticated buyer agent can rank the currently routable production
capabilities without creating an order or reserving funds:

```http
POST /payments/v1/universal/buyer/intents/preview
Authorization: Bearer ias_...
Idempotency-Key: research-btc-2026-08-16-001
Content-Type: application/json

{
  "service": "web_research",
  "goal": "Produce a cited summary of current Bitcoin market signals",
  "maximum_price": 3,
  "strategy": "safest",
  "required_capabilities": ["source_verification"]
}
```

The candidate set is built only from active seller identities, active
capabilities, healthy runtimes and active Foundation-verified catalogs. The
response explains eligible and rejected candidates, objective contributions,
risks and confidence. It exposes catalog and capability identifiers but never
seller wallets, private runtime URLs, credentials or raw execution context.

This endpoint is a preview, not a quote: it creates no order, reserves no funds
and performs no seller execution. It persists a wallet-bound decision for at
most two minutes. Replaying the same request and idempotency key returns the
same decision; changing the request under that key is rejected.

To create the selected order, commit the returned decision:

```http
POST /payments/v1/universal/buyer/intents/commit
Authorization: Bearer ias_...
Content-Type: application/json

{"intent_decision_id": "bid_..."}
```

Commit revalidates the seller identity, capability, runtime, catalog, currency
and price. Any market change invalidates the decision. A successful commit is
single-use and idempotent: retries return the same deterministic order. It
still moves no funds; the next action is the wallet checkout preparation route.

To enforce the wallet's autonomous purchase policy and prepare the exact
committed order for signature:

```http
POST /payments/v1/universal/buyer/intents/checkout/prepare
Authorization: Bearer ias_...
Content-Type: application/json

{"intent_decision_id": "bid_...", "input_asset": "USDC"}
```

The decision must belong to the authenticated wallet and already reference a
committed order. IAT creates or reuses its quote, checks the service and budget
limits, reserves the amount in the daily policy, simulates the checkout and
returns the transaction for the buyer agent's signature. IAT neither holds the
buyer's key nor signs or submits the transaction on the buyer's behalf.

After the buyer agent has reviewed, signed and broadcast that exact transaction,
it can bind the resulting Solana signature back to the intent lifecycle:

```http
POST /payments/v1/universal/buyer/intents/checkout/submit
Authorization: Bearer ias_...
Content-Type: application/json

{
  "intent_decision_id": "bid_...",
  "quote_id": "uq_...",
  "tx_signature": "..."
}
```

IAT verifies that the decision, committed order and quote all belong to the
same authenticated wallet and rejects quote substitution. This call records a
signature for later on-chain confirmation; it does not receive a private key
and does not broadcast a transaction.

Confirmation is also bound to the same intent lifecycle:

```http
POST /payments/v1/universal/buyer/intents/checkout/confirm
Authorization: Bearer ias_...
Content-Type: application/json

{"intent_decision_id": "bid_...", "quote_id": "uq_..."}
```

IAT verifies the decision/order/quote relationship again before consulting
Solana. A non-finalized transaction returns a retryable pending state. Only a
verified payment is marked confirmed and allowed to trigger the existing
seller-delivery lifecycle. The result includes the delivery state and final
receipt when they are available.

An agent can then follow the whole transaction through one wallet-authenticated
read-only resource:

```http
GET /payments/v1/universal/buyer/intents/bid_.../lifecycle
Authorization: Bearer ias_...
```

The response exposes the safe order, checkout, delivery and receipt states plus
one machine-readable `next_action`. Pending chain confirmation and delivery
states include `poll_after_seconds`; polling never creates a quote, reserves
funds, signs a transaction or retries seller execution by itself.

For bounded automation, an agent may request exactly one safe transition:

```http
POST /payments/v1/universal/buyer/intents/advance
Authorization: Bearer ias_...
Content-Type: application/json

{"intent_decision_id": "bid_...", "input_asset": "USDC"}
```

One call can prepare a policy-authorized checkout or reconfirm an already
broadcast transaction. It never loops, signs, broadcasts, or bypasses wallet
policy. At a buyer-signature boundary or while waiting for delivery it returns
a safety stop and performs no mutation. Clients must respect the returned
`poll_after_seconds` before requesting another step.

## Local non-custodial buyer runner

`AutonomousBuyerRunner` connects the one-step controller to an external wallet
adapter. The adapter exposes only its public address and a
`sign_and_broadcast(transaction_base64, review)` method; IAT never asks for a
seed phrase, private key or keypair file.

Before calling that method the runner requires a successful server simulation,
an allowed cluster, an exact fee-payer match, all non-submission safety flags,
and an explicit `TransactionApproval` decision over the transaction summary.
The default policy permits devnet only. One `step()` call never polls or loops.

### Local wallet sidecar

`LocalWalletRPCAdapter` provides a standard boundary for an agent-owned wallet
process. By default it accepts only literal loopback endpoints such as
`http://127.0.0.1:8787`; remote HTTPS requires an explicit opt-in. It calls:

```http
POST /v1/wallet/sign-and-broadcast
Authorization: Bearer <sidecar-specific-token>
```

The body contains the public wallet address, prepared transaction and reviewed
payment summary. A successful sidecar response contains `approved: true`, the
same wallet address and the public Solana transaction signature. Redirects,
identity changes and invalid signatures fail closed. The IAT session token and
all wallet key material stay outside this request.

### Reference sidecar service

`create_wallet_sidecar_app()` creates the matching local FastAPI service around
a `WalletSigningBackend`. The backend owns the approval, signature and broadcast
implementation; the sidecar has no endpoint or configuration field for a seed,
private key or keypair file.

The service authenticates its local caller, defaults to devnet, requires a
successful simulation and short expiry, deserializes the actual transaction,
checks its fee payer and required signers, then delegates once. Identical
transaction bytes return the cached public signature and are never signed or
broadcast twice. Tests use only a fake backend and never contact Solana.

### Concrete Solana RPC backend

`SolanaRPCWalletBackend` connects the sidecar to any external
`DetachedTransactionSigner` (agent wallet, HSM, or Wallet Standard bridge). It
defaults strictly to devnet and asks a separate approval policy before calling
the signer. The returned signed transaction must preserve the original message
and every pre-existing signature; the buyer signature is verified locally.

Only then does the backend call Solana `sendTransaction` with base64 encoding,
preflight enabled, `confirmed` preflight commitment and bounded retries. The RPC
signature must equal the transaction's first signature. Receipt by the RPC is
still not settlement proof: the intent confirmation endpoint remains the only
step that marks payment verified and triggers delivery.

### Attested agent-wallet signer

`AttestedHTTPSDetachedSigner` is the concrete signer contract for an agent
wallet or HSM gateway. Before sending any transaction it asks the provider to
sign a unique, domain-separated identity challenge at
`POST /v1/identity/attest` and verifies that proof against the configured
Solana address. Attestations are cached only for a short bounded period.

Transaction signing uses `POST /v1/transactions/sign`. The request binds a
random request ID, wallet address and SHA-256 transaction digest. The response
must repeat all three bindings and return the signed transaction bytes. HTTPS
is mandatory outside loopback, redirects fail closed, and the provider token is
never included in request bodies. `SolanaRPCWalletBackend` independently checks
the returned message and signature before broadcasting it.

## Key-in-hand buyer sidecar configuration

`AgentBuyerRuntimeConfig.from_env()` assembles the attested signer, bounded
approval policy, Solana RPC backend and local sidecar. It requires the wallet,
signer URL, separate signer/sidecar tokens, maximum USDC atomic amount, and exact
allowed program, treasury vault and IAT destination. Missing values fail closed.

The sidecar can be launched with:

```bash
uvicorn iat.agent_buyer_runtime:create_wallet_sidecar_from_env \
  --factory --host 127.0.0.1 --port 8787
```

`diagnose_agent_buyer_runtime()` reports missing variable names, public wallet
and policy boundaries, but never token values. The configuration has no private
key field. This release remains devnet-only.

## Local buyer-agent API

`create_buyer_agent_service_from_env()` exposes the complete bounded journey to
an AI through one local API:

- `POST /v1/intents` previews, selects and commits an order idempotently;
- `POST /v1/intents/{id}/advance` performs at most one safe lifecycle step;
- `GET /v1/intents/{id}` returns the current lifecycle and next action;
- `GET /v1/intents/{id}/result` opens delivery only when it is ready.

Launch it on loopback with:

```bash
uvicorn iat.buyer_agent_service:create_buyer_agent_service_from_env \
  --factory --host 127.0.0.1 --port 8788
```

The API requires its own `IAT_BUYER_AGENT_API_TOKEN`. The IAT wallet session,
sidecar token and signer token remain internal and are never returned. Calls do
not loop: the agent follows `next_action` and respects `poll_after_seconds`.

### Persistent bounded scheduling

Set `IAT_BUYER_SCHEDULER_DB` to a local SQLite file (the default is
`iat-buyer-jobs.sqlite3`). An intent can then be enrolled idempotently with
`POST /v1/intents/{id}/schedule`, inspected with `GET /v1/jobs/{id}`, and moved
through one due transition with `POST /v1/scheduler/run-once`.

Each scheduler cycle claims a job with a short lease, performs no more than one
protocol transition, and persists the next run time from
`poll_after_seconds`. An expired lease is recoverable after process restart.
Transport failures use bounded backoff; an exhausted attempt budget, rejected
local approval, unknown next action, invalid transaction, cluster mismatch or
wallet mismatch stops the job. The database contains lifecycle identifiers and
scheduling metadata only—never API tokens, sidecar credentials, signer tokens,
transactions or delivered results. A local supervisor or timer may invoke
`run-once`; the API intentionally creates no hidden infinite background loop.

When the scheduler is configured, `POST /v1/intents` enrolls every successfully
created intent automatically unless the caller explicitly sends
`"auto_schedule": false`. The health endpoint reports only aggregate queue
counts and never job payloads or credentials.

For continuous operation, run the independently supervisable worker:

```bash
python -m iat.buyer_agent_worker
```

`IAT_BUYER_WORKER_INTERVAL_SECONDS` controls the delay between wake-ups and
`IAT_BUYER_WORKER_BATCH_LIMIT` caps the number of claimed jobs per wake-up.
Both values have strict bounds. SIGTERM and SIGINT request a clean stop between
cycles; each cycle still performs at most one transition for each claimed job.

### Agent-readable supervision

`GET /v1/jobs` lists scheduling records with optional `state`, `limit` and
`offset` filters. Every record includes `reason_category`,
`recommended_action` and `recoverable`, so an agent does not need to interpret
internal exceptions. Results and transaction bytes are not included.

Only a job stopped because its attempt budget was exhausted can be resumed via
`POST /v1/jobs/{id}/resume` with a bounded `additional_attempts` value. Jobs
stopped by wallet identity, signature, transaction, cluster, simulation or
protocol-state controls cannot be resumed through this endpoint. This keeps
operational recovery separate from security-policy override.

`GET /v1/jobs/{id}/events` returns the ordered, paginated transition journal
for one intent. New scheduling, attempt, waiting, retry, resume, completion and
stop records are appended; previous records are never rewritten by scheduler
operations. Events contain only intent identifiers, public state/action/error
codes and timestamps. They intentionally exclude credentials, serialized
transactions, signatures, prompts and delivered content. This local audit
trail is a precursor to protocol-level signed execution evidence; it is not
itself a settlement proof.

Every new event carries `previous_hash` and `event_hash`; the job record keeps
the expected event count and chain head. `GET /v1/jobs/{id}/events/verify`
recomputes the canonical SHA-256 chain and detects modified events, broken
links, deleted tails and a mismatched head. Existing unhashed local journals
are deterministically chained during the one-time SQLite migration.

This mechanism is tamper-evident, not tamper-proof: an operator with direct
write access to the SQLite file could replace both the journal and its local
anchor. Protocol-level evidence will require an independently signed or
externally anchored head hash before it can influence settlement or
reputation.

### Wallet-attested journal heads

`AttestedHTTPSDetachedSigner.sign_evidence()` defines a separate, narrowly
scoped provider contract at `POST /v1/evidence/sign`. It accepts only a
`buyer_job_journal` identifier, SHA-256 head and observation timestamp. The
signed message is domain-separated with `IAT_AGENT_EVIDENCE_ATTESTATION_V1`,
bound to the configured Solana wallet, and verified locally before it is
accepted.

This operation signs no transaction, names no recipient or amount, consumes no
blockhash and broadcasts nothing to Solana. The signer token remains only in
the HTTPS authorization header. Arbitrary-message signing is deliberately not
supported.

The local sidecar now exposes it at `POST /v1/wallet/attest-evidence`. It
authenticates its caller, requires the configured wallet, accepts only a recent
observation, verifies the backend's Ed25519 signature independently and caches
identical requests idempotently. `LocalWalletRPCAdapter.attest_evidence()`
reconstructs and verifies the message again at the client boundary.
`SolanaRPCWalletBackend.attest_evidence()` makes no Solana RPC call because
this is an off-chain identity proof, not a transfer.

When a scheduler job completes, its final journal head is now queued for wallet
attestation in the same SQLite transaction. Attestation runs as separate work
in a later scheduler cycle, so delivery completion never depends on signer
availability. Transient adapter errors retry with bounded exponential backoff
and a ten-attempt ceiling; a changed or invalid journal fails closed. Only the
public wallet, signature, digest and observation time are persisted. Inspect
the resulting `pending`, `attesting`, `attested` or `failed` record with
`GET /v1/jobs/{id}/anchor`. This signature makes later database alteration
detectable; the protocol evidence registry below supplies the independent
publication layer.

### Protocol evidence registry

The central IAT API now accepts a completed signed journal head at
`POST /protocol/v1/evidence`. The Ed25519 signature itself authorizes the
write: the API reconstructs the domain-separated message, rejects stale,
future-dated or invalid evidence, and never accepts arbitrary evidence types.
The tuple `(wallet_address, evidence_type, evidence_id)` is immutable through
the API. Repeating the exact request is idempotent; attempting to replace its
digest returns a conflict.

Successful publication returns a deterministic receipt identifier and receipt
SHA-256. Anyone can retrieve the public proof using
`GET /protocol/v1/evidence/{evidence_id}?wallet_address={wallet}`. The registry
labels every record `evidence_only`: publication does not release funds,
approve a dispute or modify reputation.

The scheduler automatically publishes an `attested` anchor in a later,
separate cycle and then reads the public record back before accepting the
receipt. The public calls deliberately omit the buyer session token. Receipt
identifier, digest and publication timestamp are stored with the anchor, which
then becomes `published`. Transport failures use a separate ten-attempt budget
and bounded backoff, survive process restarts, and never reopen or invalidate
the completed buyer job. A signature failure remains distinct from a
`publication_failed` registry failure, making operational recovery observable
without weakening the signing boundary.

### Independent delivery binding

`POST /protocol/v1/delivery-validations/{evidence_receipt_id}` independently
correlates a registered wallet proof with protocol-owned records: buyer intent,
confirmed checkout and transaction signature, completed IAT execution, sealed
payload digest, delivery receipt and inbox opening. A missing intermediate
state returns a retryable conflict and is not frozen as a rejection. A broken
payload digest or invalid optional inbox signature produces an immutable
rejected validation instead.

Successful correlation records a deterministic validation digest and can be
read publicly with `GET /protocol/v1/delivery-validations/{receipt_id}`. The
record explicitly states `quality_verified: false` and `effect:
evidence_only`: it proves that one delivery is bound end-to-end to one signed
buyer journal, not that the delivered content satisfies the buyer's semantic
acceptance criteria. Automated quality verification is the next layer.

## Production boundary

The production buyer flow remains:

1. `GET /services`;
2. `POST /create-order`;
3. buyer-controlled token transfer;
4. `POST /buyer/verify-payment`.

An AI should validate the service, budget, seller wallet, network, token mint,
expiry and settlement policy before authorizing a transfer. High-value orders
should use a human or policy-engine approval gate.
