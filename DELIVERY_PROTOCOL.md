# IAT Final Delivery Protocol

IAT separates four facts that must never be conflated:

1. the supplier produced a result;
2. IAT sealed that exact result with a SHA-256 digest;
3. the configured channel dispatched it;
4. the authenticated buyer accepted or disputed it.

This prevents a successful execution from being reported as an accepted final
delivery before the buyer has actually received it.

## Permanent wallet inbox authentication

Order secrets are not a durable buyer identity. The permanent inbox therefore
uses a Solana wallet signature over a short-lived, domain-separated IAT login
challenge. Signing the returned UTF-8 message creates no transaction, spends
no SOL and authorizes no payment. A successful proof returns a short-lived
Bearer session; IAT stores only its SHA-256 hash.

```http
POST /payments/v1/universal/wallet-auth/challenge
{"wallet":"<Solana public key>"}

POST /payments/v1/universal/wallet-auth/session
{"challenge_id":"iwc_...","signature":"<base58 Ed25519 signature>"}

GET /payments/v1/universal/wallet-inbox
Authorization: Bearer ias_...
```

Challenges are one-time, expire after five minutes by default and are rate
limited per wallet. Sessions expire after 30 minutes by default and can be
revoked with `DELETE /payments/v1/universal/wallet-auth/session`. Wallet A
cannot enumerate or open wallet B's receipts, and all private responses use
`Cache-Control: no-store`.

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

SMTP acceptance changes the receipt only to `dispatched`: it proves that the
configured relay accepted responsibility for the message, not that the buyer's
mail server accepted it. A correlated authenticated provider event changes it
to `delivered`. The buyer may explicitly accept or dispute from either state;
that decision remains stronger evidence than a transport-provider event.

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

Mailjet SMTP messages include `X-Mailjet-Campaign` set to the unique receipt
token. This makes the message visible in Mailjet statistics and correlates its
event callback without exposing the destination publicly. Configure a strong,
independent callback secret:

```text
IAT_MAILJET_EVENT_USERNAME=iat-mailjet
IAT_MAILJET_EVENT_SECRET=<random high-entropy secret>
```

Then configure Mailjet Event Tracking to POST events to:

```text
https://<api-host>/payments/v1/universal/delivery-events/mailjet
```

using HTTP Basic authentication with the username and secret above. The
callback verifies the Basic credential, receipt token and exact recipient
before recording `sent`, `delivered`, `open`, `click`, `bounce`, `blocked`, or
`spam`. Bounce/block/spam events fail a merely dispatched receipt; they never
reverse an explicit buyer decision.

For transport-only production checks, configure one fixed external recipient:

```text
IAT_DELIVERY_CANARY_RECIPIENT=<external address distinct from the sender>
```

An authenticated administrator can then call
`POST /admin/checkout-delivery/email-canary`. The endpoint cannot accept an
arbitrary recipient: it sends one signed probe only to the environment address
and creates no order, receipt, payment, or settlement.

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

After the receipt state becomes `dispatched` or `delivered`, the buyer makes one
final, idempotent decision:

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
- `dispatched`: SMTP accepted the email but provider confirmation or buyer
  confirmation remains pending;
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
