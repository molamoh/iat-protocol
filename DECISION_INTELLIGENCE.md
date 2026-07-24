# IAT Decision Intelligence Core v2

The Decision Intelligence Core provides one deterministic decision contract for
buyers, sellers and protocol runtimes. Its first production integration powers
buyer sandbox ranking; its public endpoint remains simulation-only.

## Public simulation

`POST /intelligence/v1/decisions/simulate`

The request supplies up to 100 candidates, hard constraints and one strategy:
`balanced`, `cheapest`, `fastest`, `safest` or `quality`.

The engine:

- rejects candidates that violate price, capability, trust or reliability
  constraints;
- scores eligible candidates across price, quality, trust, reliability and
  latency;
- returns weighted contributions and factual inputs for every score;
- reports alternatives, rejected candidates and rejection reasons;
- estimates confidence from the winning margin, with a confidence cap when
  only one candidate is eligible;
- exposes risks such as a narrow margin, low trust or a single available
  candidate;
- produces a deterministic SHA-256 decision hash over the policy, candidates,
  result and caller context.

Simulation never moves funds, creates orders or invokes a candidate.

## Example

```json
{
  "decision_type": "select_offer",
  "candidates": [
    {
      "candidate_id": "seller-a",
      "price": 4.5,
      "quality": 92,
      "trust": 96,
      "reliability": 94,
      "latency_score": 75,
      "capabilities": ["search", "citations"]
    }
  ],
  "policy": {
    "strategy": "safest",
    "maximum_price": 5,
    "required_capabilities": ["citations"],
    "minimum_trust": 80,
    "minimum_reliability": 80
  },
  "context": {
    "buyer_intent_id": "intent_example"
  }
}
```

## Safety invariants

- Unknown strategies and malformed metrics fail closed.
- Metrics must be finite values from 0 to 100.
- Candidate identities must be unique.
- Hard constraints cannot be compensated for by a high score elsewhere.
- Policy and engine versions are included in every result.
- Commercial commission is not a hidden ranking objective.
- Bounded learning remains an explicit, separately reported adjustment.

## Governed outcome learning

Production outcomes are recorded through authenticated administration:

- `POST /admin/intelligence/outcomes`
- `GET /admin/intelligence/outcomes`
- `GET /admin/intelligence/calibration`

Every outcome references the 64-character decision hash and an idempotency key.
Predicted and observed utilities are bounded from 0 to 1. Conflicting replays
fail closed.

Calibration reports mean error, mean absolute error and whether the engine is
systematically overestimating or underestimating results. Drift is evaluated
only after at least 20 outcomes. A detected drift recommends a policy review in
shadow mode; the report always returns:

```json
{"policy_mutation_allowed": false}
```

## Foundation execution shadow mode

The existing Foundation execution layer remains authoritative. Decision Core v2
evaluates the same execution agents in parallel and records:

- its selected agent and complete explanation;
- whether its result diverges from Foundation;
- any shadow evaluation failure.

A shadow failure is telemetry only and cannot interrupt or replace the
Foundation decision. Promotion from shadow mode requires measured outcomes,
calibration evidence and a separate governed release.

## Seller competitive intelligence

`POST /seller/v1/intelligence/analyze` compares one seller offer with 2–100
caller-supplied market benchmarks. It returns:

- balanced competitive rank and percentile;
- median market price;
- capability gaps relative to top-quartile competitors;
- break-even price after variable cost and protocol commission;
- current, market-median and ±10% pricing scenarios;
- governed recommendations with explicit evidence.

Demand projections use the caller's baseline orders and declared price
elasticity. They are scenarios, not forecasts or revenue promises. By default,
the public API mirrors the active protocol commission. Every response states
that benchmark data is caller supplied and prohibits automatic price or catalog
changes.

## Privacy-preserving demand forecast

`POST /seller/v1/intelligence/demand/forecast` accepts only daily aggregate
counts. The strict request schema has no buyer, wallet, prompt or order identity
field.

The forecast requires:

- 14–365 contiguous daily observations;
- at least 50 aggregated events;
- a 1–30 day horizon;
- optional current capacity and a bounded headroom ratio.

It reports a bounded linear trend, weekday seasonality after 28 days, 95%
residual intervals, anomalies, and a capacity scenario based on the upper
forecast interval. Low-volume and discontinuous data fail closed.

This is an operational scenario rather than a guaranteed demand prediction.
Capacity and pricing changes remain prohibited until approved by the seller.
