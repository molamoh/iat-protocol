# IAT autonomous quote signer

The quote signer is a private, fail-closed service that authorizes an exact
Solana checkout transaction after the public API has prepared an immutable
order-bound plan. It never submits a transaction and never signs for the buyer.

## Flow

1. The buyer creates and prepares a universal checkout quote.
2. The buyer wallet builds the exact transaction from
   `solana_instruction_plan`, including a recent blockhash.
3. The wallet sends that unsigned transaction to
   `POST /payments/v1/universal/{quote_id}/authorize` with its order credential.
4. The public API loads the prepared plan from its own database and sends it to
   the private signer over an HMAC-authenticated internal request.
5. The signer rejects expired quotes, long lifetimes, lookup tables, unknown or
   repeated instructions, wrong fee payer, wrong signer set, wrong authority,
   missing blockhash, and any difference from the stored plan.
6. The signer fills only the configured `quote_authority` signature slot.
7. The buyer wallet displays and simulates the returned transaction, adds the
   buyer signature, submits it to Solana, and registers the transaction
   signature through the existing checkout API.

The signer does not trust a client-provided plan. The public API supplies the
plan persisted during `prepare`. Both services independently validate the
authorization contract.

## Safe defaults

- The service starts with `IAT_QUOTE_SIGNER_ENABLED=false`.
- Its OpenAPI and documentation routes are disabled.
- The Render Blueprint creates a private service, not a public web service.
- HMAC secrets must contain at least 32 bytes.
- Authentication timestamps have a 30-second window.
- Quote lifetime at signing is capped at 120 seconds.
- Address Lookup Tables and additional instructions are rejected.
- Requests are idempotent by deterministic request ID and exact body hash.
- The local keypair backend refuses every cluster except `devnet`.
- The service signs but never sends or confirms a Solana transaction.

## Private signer variables

```text
IAT_QUOTE_SIGNER_ENABLED=false
IAT_QUOTE_SIGNER_CLUSTER=devnet
IAT_QUOTE_SIGNER_ALLOW_LOCAL_KEYPAIR=false
IAT_QUOTE_SIGNER_SHARED_SECRET=
IAT_QUOTE_SIGNER_KEYPAIR_PATH=/etc/secrets/iat-quote-authority.json
```

The devnet keypair must be mounted as a Render secret file. Never paste it into
chat, Git, an image, logs, or a normal environment variable. The devnet quote
authority must be a dedicated wallet, distinct from the buyer, protocol admin,
deployment authority, and treasury authority.

The dedicated devnet signer public key prepared for the guarded rollout is
`3eg5d45QKsWL6ZNQ7Lp7ZJdJiQ1tzDce96SAZyb3zyyq`. Only this public key is
recorded in Git. The corresponding secret must exist exclusively in the
private Render secret file and the operator's secure backup.

The on-chain `quote_authority` was rotated to this dedicated key while GN2d
remained paused. Finalized devnet transaction:
`2ZYauoJPN9Znj6DoXjTQHHQ3Gg1Aj9KkBtv5zby1rx7c567j6BUQZuDtB2sZLX9ikgqsozgun1uhGVtyKNB3bjUB`.
The administrative authority and both treasury vault balances were unchanged.

GN2d was then upgraded at devnet slot `480260481` to enforce this signer on the
direct purchase instruction. Finalized transaction:
`fBujWdJP8NCASSJrstt2jk41SH9epbeHpejNWD8hxo4tfZzdWkHeubr9bCjKnMaHNXfrbymwmjtund4fJXkRyjw`.
The verified executable hash is
`d2d8cdc0a9632333aea0d941e1f609271c984e27e7b29dc99c45bedd0b47549b`.

The file backend is a devnet canary mechanism only. Mainnet activation requires
a backend that delegates `sign_message` to an HSM/KMS or equivalent
non-exportable signing system, durable replay/audit storage, independent
monitoring, and an external security review.

## Public API variables

```text
IAT_QUOTE_SIGNER_CLIENT_ENABLED=false
IAT_QUOTE_SIGNER_URL=
IAT_QUOTE_SIGNER_SHARED_SECRET=
IAT_QUOTE_SIGNER_TIMEOUT_SECONDS=8
IAT_QUOTE_SIGNER_ALLOW_HTTP_PRIVATE=false
```

The shared secret must be identical on both services. Internal clear-text HTTP
is rejected unless `IAT_QUOTE_SIGNER_ALLOW_HTTP_PRIVATE=true` is explicitly set
for a platform-encrypted private network.

## Rollout order

GN2d must remain paused throughout rollout:

1. deploy the signer disabled and verify `/health`;
2. install the dedicated devnet signer secret and shared HMAC secret;
3. rotate on-chain `quote_authority` to the dedicated signer public key;
4. upgrade GN2d to the matching two-signature binary;
5. deploy the matching public API image;
6. enable private signer and public signer client;
7. build an unsigned canary, authorize it, and simulate it;
8. request explicit approval before unpausing or sending any canary;
9. return GN2d to pause after the canary.

Do not deploy the updated public API against the old GN2d binary: its direct
instruction has one additional signer account and is intentionally
incompatible.
