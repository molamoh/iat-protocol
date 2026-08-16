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

## Production boundary

The production buyer flow remains:

1. `GET /services`;
2. `POST /create-order`;
3. buyer-controlled token transfer;
4. `POST /buyer/verify-payment`.

An AI should validate the service, budget, seller wallet, network, token mint,
expiry and settlement policy before authorizing a transfer. High-value orders
should use a human or policy-engine approval gate.
