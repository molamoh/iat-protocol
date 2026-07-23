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

## Production boundary

The production buyer flow remains:

1. `GET /services`;
2. `POST /create-order`;
3. buyer-controlled token transfer;
4. `POST /buyer/verify-payment`.

An AI should validate the service, budget, seller wallet, network, token mint,
expiry and settlement policy before authorizing a transfer. High-value orders
should use a human or policy-engine approval gate.
