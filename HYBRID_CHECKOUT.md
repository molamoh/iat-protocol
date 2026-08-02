# IAT Hybrid Checkout

Status: policy, reservation, discovery, API, SDK, Anchor program, and unsigned
instruction-plan adapter implemented; the program is compiled but not deployed.

## Purpose

An existing IAT order can be paid with an allowlisted Solana asset. The engine
selects exactly one route:

1. treasury inventory, if every inventory, price, wallet, order, and daily
   limit passes;
2. an allowlisted Raydium pool, only if the treasury route is unavailable and
   liquidity, price impact, freshness, output, and reference-price deviation
   all pass;
3. fail closed.

The treasury is not an exchange desk. IAT output is restricted to the order
settlement escrow and cannot be withdrawn to the buyer. A quote cannot exist
without an existing payable order and matching buyer wallet plus order secret.

## Implemented safety invariants

- Exact IAT output is derived from the stored order; the client cannot choose it.
- Quotes bind order, buyer wallet, input mint, amount, route, timestamps, and a
  SHA-256 intent hash.
- Idempotency keys are mandatory and conflicting reuse returns HTTP 409.
- Reservations count against wallet, treasury, inventory, and per-order caps.
- Reservations are serialized by a process lock and a PostgreSQL advisory lock.
- Oracle and Raydium snapshots expire; stale inputs fail closed.
- Raydium pools and token mints are allowlisted.
- Raydium is market evidence and a fallback, never the IAT reference oracle.
- The API never accepts a destination for IAT and never handles a private key.
- The buyer must inspect and sign; simulation is required before submission.

With the currently reported Raydium liquidity of about USD 80, the default
minimum liquidity of USD 10,000 intentionally rejects the Raydium route.

## API flow

After creating an order:

```text
POST /payments/v1/universal/quote
Idempotency-Key: a-unique-key-at-least-16-characters

{
  "order_id": "...",
  "buyer_wallet": "...",
  "buyer_secret": "...",
  "input_asset": "USDC"
}
```

Then prepare the selected quote:

```text
POST /payments/v1/universal/{quote_id}/prepare

{
  "buyer_wallet": "...",
  "buyer_secret": "..."
}
```

After the wallet has displayed and simulated the transaction, it signs and
submits directly to Solana. The public signature is then registered:

```text
POST /payments/v1/universal/{quote_id}/submit

{
  "buyer_wallet": "...",
  "buyer_secret": "...",
  "tx_signature": "..."
}
```

Confirmation is a separate idempotent operation:

```text
POST /payments/v1/universal/{quote_id}/confirm

{
  "buyer_wallet": "...",
  "buyer_secret": "..."
}
```

The state machine is `quoted → prepared → submitted → confirmed`. Expired
quotes cannot be submitted. A transaction not yet finalized remains
`submitted` and returns a retryable `pending` result. A finalized failed or
cryptographically mismatched transaction becomes `failed`.

Status credentials are headers, so the order secret does not enter URL logs:

```text
GET /payments/v1/universal/{quote_id}

POST /payments/v1/universal/{quote_id}/deliver

Relance explicitement une livraison devenue éligible après son délai de reprise.
Cette opération ne revalide pas et ne réutilise jamais le paiement.

La livraison est aussi reprise automatiquement par un worker persistant. Les
réplicas se coordonnent avec des baux en base : un seul exécute une tentative,
les pannes temporaires suivent un backoff exponentiel, et le paiement reste
dans l'état `paid` jusqu'à une livraison ou une décision Foundation terminale.

Variables de contrôle :

- `IAT_CHECKOUT_DELIVERY_WORKER_ENABLED` (`true` par défaut)
- `IAT_CHECKOUT_DELIVERY_POLL_SECONDS` (10)
- `IAT_CHECKOUT_DELIVERY_BATCH_SIZE` (20)
- `IAT_CHECKOUT_DELIVERY_LEASE_SECONDS` (90)
- `IAT_CHECKOUT_DELIVERY_MAX_ATTEMPTS` (8)
- `IAT_CHECKOUT_DELIVERY_RETRY_BASE_SECONDS` (30)

Chaque fournisseur doit traiter le couple stable `order_id` /
`tx_signature` comme clé d'idempotence. Le protocole empêche les exécutions
concurrentes ; cette clé protège aussi la reprise après l'arrêt brutal d'un
worker ayant déjà appelé un système externe.

## IAT Delivery Inbox

Le résultat destiné à l'acheteur est filtré par liste blanche, sérialisé en
JSON canonique, scellé par SHA-256 et conservé dans l'inbox native IAT. Quand
`IAT_DELIVERY_SIGNING_KEYPAIR_PATH` est configuré, cette même représentation
canonique est signée par l'autorité Ed25519 de livraison et la signature ainsi
que sa clé publique sont persistées avec le reçu. Une clé configurée mais
illisible fait échouer le scellement au lieu de produire silencieusement une
preuve non signée. Le
jeton de capacité aléatoire `cdr_...` permet de consulter le reçu puis le
contenu sans placer le secret buyer dans l'URL :

```text
GET /payments/v1/universal/delivery-receipts/{receipt_token}
GET /payments/v1/universal/delivery-receipts/{receipt_token}/inbox
POST /payments/v1/universal/delivery-receipts/{receipt_token}/decision
```

Un acheteur ou agent peut aussi retrouver toutes les livraisons rattachées à
son wallet, même s'il n'a plus le secret d'une ancienne commande. IAT émet un
challenge court et à usage unique ; le wallet signe exactement le message
retourné, sans transaction Solana, frais ni autorisation de paiement :

```text
POST /payments/v1/universal/wallet-auth/challenge
{"wallet":"..."}

POST /payments/v1/universal/wallet-auth/session
{"challenge_id":"iwc_...","signature":"<base58 Ed25519>"}

GET /payments/v1/universal/wallet-inbox
GET /payments/v1/universal/wallet-inbox/{quote_id}
Authorization: Bearer ias_...

DELETE /payments/v1/universal/wallet-auth/session
Authorization: Bearer ias_...
```

Le challenge expire après 5 minutes, ne peut être utilisé qu'une fois et est
limité en fréquence par wallet. La session expire après 30 minutes par défaut,
est révocable et seul son SHA-256 est stocké. Les réponses privées interdisent
la mise en cache. Les durées peuvent être ajustées dans leurs limites de
sécurité avec `IAT_WALLET_CHALLENGE_TTL_SECONDS` et
`IAT_WALLET_SESSION_TTL_SECONDS`.

Les anciennes routes à secret de commande restent provisoirement disponibles
pour compatibilité :

```text
GET /payments/v1/universal/buyer-inbox
GET /payments/v1/universal/buyer-inbox/{quote_id}
X-IAT-Buyer-Wallet: ...
X-IAT-Order-Secret: ...
```

La liste est paginée par curseur stable et la jointure SQL exige que le wallet
prouvé soit celui de la commande propriétaire. Les reçus canaris et ceux
d'autres buyers ne peuvent pas apparaître. La récupération authentifiée par
`quote_id` ne retourne pas le jeton de capacité `cdr_...`; celui-ci reste
réservé au lien de portail explicitement fourni dans la liste.

L'ouverture de l'inbox est auditée une seule fois, utilise `Cache-Control:
no-store` et ne vaut jamais acceptation. Le portail recalcule l'empreinte du
JSON canonique puis vérifie la signature Ed25519 IAT avant d'afficher le
résultat. Les anciens reçus sans signature restent identifiés comme tels. Le
règlement reste bloqué jusqu'à
une décision explicite de l'acheteur.

Le reçu passe à `delivered` dès que l'inbox native est disponible. L'e-mail ou
le webhook configuré devient une notification secondaire : son échec, sa
suspension ou l'absence d'un fournisseur SMTP ne rétrograde jamais la
livraison IAT et ne bloque jamais l'accès au résultat. Son état distinct est
exposé par `notification_status` (`pending`, `dispatched`, `confirmed` ou
`failed`).

## Supervision et reprise

Les routes suivantes exigent `IAT_ADMIN_API_KEY` via l'en-tête `x-api-key` :

- `GET /admin/checkout-delivery/dashboard`
- `GET /admin/checkout-delivery/{quote_id}/events`
- `POST /admin/checkout-delivery/{quote_id}/redrive`

Le dashboard ne retourne ni secret buyer, ni contenu de livraison, ni
transaction brute. Une redrive n'est permise que depuis `exhausted`, exige un
motif de 8 à 500 caractères et produit un événement d'audit immuable.

## Allocation après livraison

Une livraison réussie crée une seule allocation de règlement par `order_id`.
Cette allocation calcule la commission et la part seller, mais ne signe et ne
diffuse aucune transaction. Le pipeline de gouvernance du règlement conserve
l'autorité exclusive de libérer l'escrow.

La reprise d'une allocation en erreur possède sa propre boucle et ne rappelle
jamais le fournisseur. Les états de livraison et de règlement sont donc
indépendants, visibles dans le dashboard et sûrs face aux redémarrages.

## Compensation d'une non-livraison

Une livraison `exhausted` ou `foundation_delivery_blocked` ouvre
automatiquement une demande de compensation. Le buyer authentifié peut aussi
effectuer une demande idempotente :

`POST /payments/v1/universal/{quote_id}/compensation/request`

La politique dépend de la route :

- Treasury : restitution de l'actif d'entrée et du montant exact encaissé ;
- Raydium : restitution de l'IAT exact reçu dans l'escrow. Le protocole ne
  promet pas de recréer le cours initial de l'actif vendu.

Les contrôles Foundation sont protégés par `IAT_ADMIN_API_KEY` :

- `GET /admin/checkout-compensation/dashboard`
- `POST /admin/checkout-compensation/{quote_id}/decision`

Une décision exige un motif audité. `approved` signifie que le remboursement
est autorisé, pas qu'il a été diffusé : l'ordre ne devient jamais `refunded`
sans une future preuve de transfert on-chain finalisée vers le wallet buyer.
X-IAT-Buyer-Wallet: ...
X-IAT-Order-Secret: ...
```

`prepare` returns the immutable transaction contract and, when every on-chain
address and price ratio is configured, the exact Anchor instruction data and
ordered account metas. The buyer wallet must obtain a recent blockhash, include
wallet-usage initialization only when that PDA is absent, simulate, display,
sign, submit, and confirm the transaction. The API never signs it.

## Server configuration

All routes fail closed by default.

```text
IAT_TREASURY_CHECKOUT_ENABLED=false
IAT_RAYDIUM_CHECKOUT_ENABLED=false
IAT_TOKEN_ADDRESS=
IAT_REFERENCE_PRICE_USD=0
IAT_TREASURY_INVENTORY_IAT=0
IAT_TREASURY_PROGRAM_ID=
IAT_TREASURY_QUOTE_AUTHORITY=
IAT_TREASURY_IAT_VAULT=
IAT_TREASURY_SETTLEMENT_ESCROW=
IAT_IAT_TOKEN_PROGRAM=TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA
IAT_CHECKOUT_MAX_ORDER_IAT=100
IAT_CHECKOUT_WALLET_DAILY_IAT_CAP=250
IAT_TREASURY_DAILY_IAT_CAP=1000
IAT_TREASURY_SPREAD_BPS=50
IAT_CHECKOUT_QUOTE_TTL_SECONDS=60
IAT_CHECKOUT_ORACLE_MAX_AGE_SECONDS=90
IAT_RAYDIUM_MAX_PRICE_IMPACT_BPS=300
IAT_RAYDIUM_MIN_LIQUIDITY_USD=10000
IAT_CHECKOUT_MAX_REFERENCE_DEVIATION_BPS=500
IAT_RAYDIUM_ALLOWED_POOLS=
IAT_RAYDIUM_ALLOWED_PROGRAMS=
IAT_RAYDIUM_LIVE_ENABLED=false
IAT_RAYDIUM_SLIPPAGE_BPS=100
IAT_RAYDIUM_TIMEOUT_SECONDS=8
IAT_RAYDIUM_COMPUTE_UNIT_PRICE_MICRO_LAMPORTS=50000
IAT_CHECKOUT_SOLANA_RPC_URL=
IAT_CHECKOUT_RPC_TIMEOUT_SECONDS=10
IAT_CHECKOUT_RPC_MAX_ATTEMPTS=3
IAT_CHECKOUT_RPC_RETRY_DELAY_SECONDS=0.5
IAT_CHECKOUT_ASSETS_JSON={}
IAT_RAYDIUM_QUOTES_JSON={}
```

`IAT_TOKEN_ADDRESS` defaults to the canonical mainnet mint. Deployments on
another cluster must override it explicitly; an empty value falls back to the
mainnet mint and therefore cannot silently select an invalid token.

### Current devnet deployment

The checkout program and its initial paused configuration are deployed on
Solana devnet:

```text
Program:                 GN2d9tgQvwWqFaGuVomqBxcngW8c3CPWe4JRG6bP4rD
Config PDA:              fWaLoVxfaex7feYLfYWH4hs8i42ju56M8iZ2vxqjGid
Vault authority PDA:     BmCjmMWzY4GrSBwMEnAisqrvBj8duSc7pg73DiGwarwH
IAT mint:                2ZT8Yh4kPYCJ8BQmx6uNPCAXVUHqQF8rd8h7cia5UeD7
Treasury IAT vault:      5suHr716G6W2tvswJmDmUYjwwMVpcZLEKhUHAXQnPX9n
Settlement escrow:       DELbTQnbDk3ua1bUJWPpBgbxzKBQjJUN9EGzcPKk36SX
Authority/quote signer:  EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc
USDC devnet mint:        4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU
Treasury USDC vault:     jDvREhHHJuwveKZJPAa2WbzhHktkkn9qdcvMXCdX95j
USDC asset policy PDA:   DAm5ka4UL5ueC9PtHaFmunugXHt2Mbtr2SUvgTspZujr
Test buyer usage PDA:    36XKisX19UmwRhuiHiy2p9EuftNpW3EaJeMmZW8s8BCb
```

The mint uses the classic SPL Token program with 8 decimals, no freeze
authority, and an initial 10,000 test-IAT inventory in the PDA-controlled
treasury vault. Protocol limits are 100 IAT per order, 250 IAT per wallet per
day, and 1,000 IAT treasury output per day. The Circle USDC devnet mint uses
the classic SPL Token program with 6 decimals. The PDA-controlled USDC vault
holds 10 test-USDC, while the test buyer retains 10 test-USDC. Its durable
asset account is configured for a 201/20,000 minor-unit ratio, equivalent to
1.005 USDC per IAT, and a 100 IAT order cap. Asset-policy timestamps expire
after at most 900 seconds and must be refreshed immediately before a smoke
test. The protocol remains paused and both public checkout routes remain
disabled until that controlled activation.

Asset and Raydium JSON values are trusted server-side adapter snapshots, never
client input. Each treasury asset contains `mint`, `decimals`, `usd_price`,
`oracle`, `observed_at`, `token_program`, `treasury_vault`,
`onchain_ratio_numerator`, and `onchain_ratio_denominator`. The ratio is
expressed as input minor units per IAT minor unit. The adapter refuses to emit
an instruction if the quoted amount does not exactly match that ratio.
Production must refresh price configuration through an authenticated,
governance-controlled oracle process; changing environment variables manually
is only suitable for controlled tests.

The program was upgraded at devnet slot `479798767` with explicit CPI target
constraints that accept only the classic SPL Token program. Token-2022 assets
are rejected until extension-aware accounting is implemented. The verified
executable hash is
`3f25c7a204022e4da453b508c2f545ae2f12e2b9b31cfbbbaf883e7e3d9164eb`.
The protocol remains paused after this upgrade; price refresh and unpause are
separate controlled operations.

The controlled post-upgrade canary completed on 2026-07-29. Transaction
`3Jg3pEs9w8xVefi9eB3ePvUyZPVcYivPTmrp9Jw3mpxSXwQEWVzu565YPUCt4777cWA5rKASikVtNr7waMUdCHLX`
atomically exchanged 1.005 devnet USDC for 1 test IAT through the hardened
program and was independently confirmed by the checkout API. The protocol was
then returned to `paused=true` by finalized transaction
`3AjzQLtxUf7B2HuY3k6NAxB2sStf2UWbuA17GDTcgiNnEmboozU58Cni6iN5SN3NRiktpuirKeJ6oWBvLuRTmKLt`.
Post-canary vault inventories are 13.5175 devnet USDC and 9,996.5 test IAT.
Read-only deployment verification retries bounded transient RPC failures, but
transaction senders never automatically resubmit after an ambiguous result.

### Quote-authorization hardening

The current devnet program requires the configured `quote_authority` signer
for direct USDC-to-buyer purchases. This closes the gap where a buyer could
construct a valid fixed-price purchase without an API-issued order and consume
treasury inventory within the on-chain caps. The candidate binary is 420,800
bytes with SHA-256
`d2d8cdc0a9632333aea0d941e1f609271c984e27e7b29dc99c45bedd0b47549b`.
It was deployed at devnet slot `480260481` by finalized transaction
`fBujWdJP8NCASSJrstt2jk41SH9epbeHpejNWD8hxo4tfZzdWkHeubr9bCjKnMaHNXfrbymwmjtund4fJXkRyjw`.
The first 420,800 on-chain ProgramData bytes exactly match the candidate hash;
the remaining 4,672 allocated bytes are zero padding. The deployment buffer was
closed automatically and its 2.92997208 SOL returned. GN2d remained paused.

Rollout must now deploy the matching API/client image plus external
quote-signing service, verify both versions, and only then run a separately
approved canary. Unpausing without the quote-signing service is forbidden.

The isolated signer architecture and guarded rollout are documented in
`QUOTE_SIGNER.md`.

## Raydium fallback

The live adapter uses Raydium Trade API Route V2 exact-output endpoints:

1. `GET https://api-v3.raydium.io/pools/info/ids` verifies the pool ID, its
   Raydium program, both mints, and current TVL;
2. `GET /compute/swap-base-out` asks for the exact IAT minor-unit amount;
3. IAT validates mints, one-hop route, single allowlisted pool, price impact,
   maximum input, reference deviation, liquidity, and the roughly 30-second
   provider lifetime;
4. `POST /transaction/swap-base-out` requests a `LEGACY` transaction whose
   output account is the protocol settlement escrow;
5. IAT deserializes the transaction and validates fee payer, only buyer signer,
   writable payment accounts, exact account set, one allowlisted Raydium
   instruction, no unknown top-level program, no buyer IAT ATA, and no provider
   signature;
6. the buyer wallet must display, simulate, sign, submit, and confirm it.

Live Raydium quotes expire after at most 25 seconds. Multiple transactions,
address lookup tables, multi-hop routes, native-SOL wrapping, referral transfers,
and arbitrary output accounts are deliberately rejected in v1. This narrower
surface is less convenient but materially easier to audit.

The live read-only verification performed on 2026-07-24 identified the active
IAT/USDC pool as `Bnw1xc1eQo5savfAzmoJoM3QNYM9u6M8WYzDm5aZeBsE`, using Raydium
CPMM program `CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C`. Its reported TVL
was about USD 165.52, far below the default USD 10,000 safety threshold.
Consequently the live engine correctly refuses this route today. These
addresses are observations, not permission to enable mainnet automatically.

## Finalized verification

Client callbacks and balance-only evidence are never trusted.

- Raydium confirmation fetches the finalized base64 transaction from Solana and
  requires its first signature, buyer fee payer, and SHA-256 message hash to
  match the exact transaction prepared by IAT.
- Treasury confirmation requires the finalized transaction to reference the
  configured checkout program and exact `PaymentIntent` PDA. The account must
  be owned by that program, non-executable, have the Anchor discriminator and
  exact length, and match order hash, quote hash, buyer, input mint, both
  amounts, and nonce.
- Confirmation atomically consumes the signature in the protocol-wide
  `processed_txs` registry, moves the quote to `confirmed`, and marks the order
  `paid`. A signature cannot settle two checkout quotes or be reused by the
  legacy direct-IAT payment path.

## Solana program

The Anchor 0.32.1 program is in `programs/iat-checkout`. Its devnet program
address is `GN2d9tgQvwWqFaGuVomqBxcngW8c3CPWe4JRG6bP4rD`.

It implements:

- one `ProtocolConfig` PDA containing governance authority, pause flag, IAT mint,
  fixed token program IDs, price/cap policy version, and approved assets;
- one isolated `TreasuryVault` token account per accepted mint and an IAT vault
  controlled by a PDA, with governance held by a multisig;
- one `PaymentIntent` PDA derived from protocol domain, order ID hash, buyer,
  and nonce;
- an instruction that verifies buyer signer, order/intent hash, exact input,
  minimum IAT output, expiry, mint allowlist, limits, and unused nonce;
- a single atomic transfer of buyer input to treasury and IAT from treasury to
  the protocol order-settlement escrow;
- no arbitrary destination account, token program, CPI program, or Raydium pool;
- canonical PDA bumps, typed account owners, duplicate mutable-account checks,
  checked arithmetic, pause authority, and immutable replay consumption.

The program starts paused, requires explicit per-asset configuration, maintains
daily wallet and global treasury counters on-chain, supports SPL Token and
Token-2022 through fixed typed interfaces, and uses a two-step authority
transfer. It contains no Raydium CPI and accepts no arbitrary program target.

Every treasury execution requires two independent signatures:

- the buyer signs as fee payer and authorizes spending the input asset;
- the configured `quote_authority` signs the exact same transaction to prove
  that IAT issued this order-bound quote.

The quote authority must be an external HSM, multisig, or wallet signing
service. The API does not store its key. A compromised quote authority still
cannot spend buyer funds without the buyer signature, change the governed price,
bypass caps, redirect IAT outside settlement escrow, or select other vaults.

Local validation:

```text
NO_DNA=1 cargo test -p iat-checkout
NO_DNA=1 anchor build
```

Raydium execution should first use Raydium's official transaction builder
adapter with fixed pool and program IDs. If a future CPI is introduced, all
program and pool accounts must be matched against configuration; arbitrary CPI
targets are forbidden.

Before mainnet: implement the Anchor program, run unit tests with LiteSVM or
Mollusk, integration tests against a local Surfpool/devnet environment, perform
an independent security review, fund strict test caps, and run a human-approved
canary. No server or CI secret should contain a treasury seed phrase.
