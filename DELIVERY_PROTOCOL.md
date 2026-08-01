# IAT Final Delivery Protocol

IAT separates four facts that must never be conflated:

1. the supplier produced a result;
2. IAT sealed that exact result with a SHA-256 digest;
3. the configured channel dispatched it;
4. the authenticated buyer accepted or disputed it.

This prevents a successful execution from being reported as an accepted final
delivery before the buyer has actually received it.

## Configure the final channel

The buyer authenticates with the same wallet and order secret used by checkout:

```http
POST /payments/v1/universal/{quote_id}/delivery-destination
Content-Type: application/json

{
  "buyer_wallet": "...",
  "buyer_secret": "...",
  "channel": "api_pull",
  "destination": null
}
```

Supported channel contracts:

- `api_pull`: the authenticated checkout status response carries the result;
- `email`: validated destination, stored privately and returned only in masked form;
- `webhook`: HTTPS destination without embedded credentials.

Email and webhook are accepted as delivery contracts and remain in
`pending_dispatch` until their transport adapter records a successful send.
They are never falsely marked delivered merely because execution completed.

### Signed webhook dispatch

The webhook adapter is autonomous and durable. It validates the destination as
a public HTTPS runtime, disables redirects, uses bounded timeouts and retries
with exponential backoff. The exact canonical JSON body remains unchanged
across retries and uses the receipt ID as `Idempotency-Key`.

Every request includes:

- `X-IAT-Delivery-Signature`: Ed25519 signature of the exact request body;
- `X-IAT-Delivery-Signer`: public key used to verify it;
- `X-IAT-Delivery-Timestamp`: timestamp of the current transport attempt.

Configure a dedicated Solana JSON keypair file, distinct from payment keys:

```text
IAT_DELIVERY_SIGNING_KEYPAIR_PATH=/etc/secrets/iat-delivery-authority.json
IAT_DELIVERY_DISPATCH_MAX_ATTEMPTS=8
```

Only HTTP `2xx` changes the receipt to `delivered`. Network failures and
non-`2xx` responses retain a safe error code and schedule another attempt.

### Transactional email dispatch

The e-mail adapter uses standard SMTP rather than a mandatory proprietary API.
It requires TLS by default and can work with any compatible provider. Each
message has a stable `Message-ID`, the sealed result, its SHA-256 digest, an
Ed25519 signature and the public verification key.

```text
IAT_DELIVERY_SMTP_HOST=smtp.example.com
IAT_DELIVERY_SMTP_PORT=587
IAT_DELIVERY_SMTP_USERNAME=...
IAT_DELIVERY_SMTP_PASSWORD=...
IAT_DELIVERY_SMTP_STARTTLS=true
IAT_DELIVERY_SMTP_SSL=false
IAT_DELIVERY_EMAIL_FROM=IAT Delivery <delivery@example.com>
IAT_PUBLIC_SITE_URL=https://iat-protocol.pages.dev
```

The review URL stores its high-entropy receipt credential in the browser URL
fragment. Fragments are not sent to Cloudflare Pages, referrers or Web
Analytics. Loading the page performs a read-only lookup; acceptance or dispute
always requires a separate explicit `POST`.

Public receipt routes:

```text
GET  /payments/v1/universal/delivery-receipts/{receipt_token}
POST /payments/v1/universal/delivery-receipts/{receipt_token}/decision
```

## Confirm or dispute

After the receipt state becomes `delivered`, the buyer makes one final,
idempotent decision:

```http
POST /payments/v1/universal/{quote_id}/delivery/decision
Content-Type: application/json

{
  "buyer_wallet": "...",
  "buyer_secret": "...",
  "decision": "accepted",
  "message": ""
}
```

For a dispute, `decision` is `disputed`, `dispute_code` is one of
`not_received`, `incomplete`, `incorrect`, `unreadable`, or `other`, and the
buyer supplies a meaningful explanation. Once recorded, an acceptance cannot
be changed into a dispute and a dispute cannot be changed into an acceptance.

## Conflict evidence

The public receipt exposes:

- channel and masked destination;
- immutable payload digest;
- payload-ready and dispatch timestamps;
- acceptance or dispute timestamp;
- dispute classification without exposing the buyer's private explanation.

The next implementation stage adds durable email and signed-webhook dispatch,
delivery attempts, provider receipts, autonomous retries and dispute policy.

## Settlement and dispute gate

For receipt-enabled universal checkouts, final delivery confirmation is now an
input to settlement release governance:

- `accepted`: the Foundation release policy may continue its normal checks;
- `delivered`: release is blocked while buyer confirmation is pending;
- `pending_dispatch`: release is blocked because the final channel has not
  acknowledged delivery;
- `dispatch_failed`: release is blocked because final delivery failed;
- `disputed`: release is blocked and a governed compensation review is opened.

The receipt gate never reverses a finalized buyer payment and never approves a
refund by itself. A dispute creates a `pending_review` compensation request so
the sealed digest, delivery audit trail and buyer explanation can be evaluated.
Legacy non-checkout settlements without a final receipt retain their existing
governance behavior.
