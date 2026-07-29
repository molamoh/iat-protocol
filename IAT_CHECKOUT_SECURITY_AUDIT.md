# IAT checkout pre-mainnet security review

Scope: `programs/iat-checkout`, with the current product limited to direct
USDC-to-IAT purchases and the governed treasury checkout. This is an internal
review, not an independent third-party audit.

## Security properties confirmed

- the singleton configuration and all asset, usage, vault-authority, and
  payment PDAs use canonical seeds and stored bumps;
- administrative changes require the configured authority, with a two-step
  authority transfer;
- governed checkout requires the configured quote-authority signature;
- input and output token accounts are constrained by mint and authority;
- configured treasury vault addresses are enforced;
- each payment is buyer, order, and nonce bound, and `init` prevents replay;
- zero amounts and hashes are rejected;
- price policies expire within 15 minutes and use exact integer arithmetic
  rounded up in favor of the treasury;
- order, wallet, and treasury limits fail before token CPIs;
- both token transfers are atomic in one Solana transaction.

## Findings and required controls

### High: Token-2022 extensions could violate exact-settlement assumptions

Anchor's `TokenInterface` accepts both classic SPL Token and Token-2022.
Transfer-fee or transfer-hook extensions could make the credited balance differ
from the requested amount or add an unexpected CPI surface.

Mitigation implemented: all initialization, configuration, and purchase paths
now require the classic SPL Token program. Token-2022 must remain unsupported
until extension-aware balance-delta checks and an explicit allowlist exist.

### High operational: first initialization controls the singleton

The first successful `initialize_config` caller becomes protocol authority.
That is normal for a singleton Anchor program but creates an initialization
race after a fresh deployment.

Required mainnet procedure: deploy and initialize in one controlled release
window, verify the config authority/mints/vaults on-chain before unpausing, and
keep the program paused by default. Do not publish an uninitialized mainnet
program as ready.

### Medium: direct purchase has no protocol quote signer

`purchase_iat_with_usdc` intentionally uses the administrator-governed asset
ratio rather than a per-order quote signature. A buyer chooses its order hash,
nonce, and quote hash, but cannot choose the price or bypass inventory and
daily limits.

Required product rule: expose this instruction only while its asset policy is
fresh and treat the on-chain ratio as the complete public offer. Use
`execute_treasury_checkout` whenever pricing or order terms require individual
protocol authorization.

### Medium operational: one hot authority can change price and unpause

The program enforces the authority correctly, but compromise of that key can
configure a malicious ratio, redirect a newly configured input vault, or
unpause the protocol.

Required mainnet procedure: make `authority` a reviewed multisig, keep
`quote_authority` separate, alert on every config/asset mutation, and maintain
an independently controlled pause runbook.

### Medium: unit tests do not exercise full account/CPI adversarial cases

Current Rust tests cover arithmetic and limits but not complete instruction
execution with malformed PDAs, token accounts, replay attempts, wrong programs,
or concurrent cap usage.

Required before mainnet: add LiteSVM/Mollusk integration tests for every account
constraint and failure path, then obtain an independent audit.

## Devnet release gate

Before upgrading devnet:

1. build reproducibly and compare the program ID;
2. simulate the upgrade and every configuration transaction;
3. verify both USDC and IAT mints are owned by classic SPL Token;
4. run one direct purchase and one governed checkout;
5. confirm exact balance deltas, payment intent contents, and daily counters;
6. keep the program paused if any invariant differs.

No mainnet release is approved by this document.

## Devnet hardening deployment

The classic-SPL-only hardening was deployed to GN2d on devnet on 2026-07-29.

- program: `GN2d9tgQvwWqFaGuVomqBxcngW8c3CPWe4JRG6bP4rD`;
- deployment slot: `479798767`;
- upgrade signature:
  `4DiDEgG8w9ynUxM5RJeCa4vZzGTgRQb4KeoCUwZMuSnTqaycrwovubYWJFT9zWSEKeLa2PSEp8qQ9zHN7DaMVpPh`;
- local and on-chain executable SHA-256:
  `3f25c7a204022e4da453b508c2f545ae2f12e2b9b31cfbbbaf883e7e3d9164eb`;
- the remaining ProgramData capacity is zero padding;
- the protocol remained paused after the upgrade;
- no deployment buffers remained under the upgrade authority.

The USDC asset policy was stale at verification time. Refreshing that policy
and unpausing are separate transactions and were not part of this upgrade.

## Repeatable read-only verification

Run the devnet invariant verifier before preparing any upgrade:

```text
iat_env/bin/python scripts/verify_checkout_devnet.py
```

It performs only `getAccountInfo` calls. It validates account existence,
ownership, exact data length, Anchor discriminators, canonical PDA bumps, mint
and vault relationships, and classic SPL Token ownership. It never loads a
wallet, signs a transaction, or prints the configured RPC URL.

The verifier reports `upgrade_ready: false` while the protocol is unpaused.
Pausing is a separate on-chain transaction and still requires explicit
approval, simulation, and signature before an upgrade can be attempted.

An unsigned, non-mutating pause simulation is available separately:

```text
iat_env/bin/python scripts/simulate_pause_checkout_devnet.py
```

It uses a zero signature with RPC signature verification disabled. The script
does not load a wallet and contains no send-transaction code path.
