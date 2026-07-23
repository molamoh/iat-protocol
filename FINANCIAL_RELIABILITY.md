# Financial Reliability

IAT schema version 2 introduces an exact, append-only double-entry allocation
ledger around settlement creation.

## Safety properties

For every newly recorded settlement:

```text
gross amount = seller payout + protocol commission
total debits = total credits
```

The settlement row and ledger journal are committed in the same database
transaction. If the split is invalid or any ledger entry fails, neither the
settlement nor the journal is committed.

Other enforced properties:

- IAT ledger values use integer minor units with 8 decimals.
- One `order_id` can create at most one settlement.
- One settlement allocation can create at most one ledger transaction.
- Reusing an idempotency key with different content is rejected.
- State transitions use compare-and-swap semantics.
- Reconciliation detects missing, unbalanced, or amount-mismatched journals.

The original `REAL` settlement columns remain for backward compatibility.
The new `*_amount_minor` columns are authoritative for exact arithmetic on new
records.

## Ledger accounts

The initial allocation event uses:

- `iat:settlement_clearing` — debit for the gross allocation;
- `iat:seller_payable:{seller_id}` — credit for the seller obligation;
- `iat:protocol_commission_revenue` — credit for protocol commission.

An allocation journal is an internal accounting record. It is not proof of an
on-chain transfer. Blockchain submission and confirmation remain controlled by
the settlement execution state machine.

## Administrative reconciliation

All routes require the fail-closed administrator key.

```bash
curl \
  -H "x-api-key: $IAT_ADMIN_API_KEY" \
  "http://localhost:8000/admin/ledger/reconciliation?limit=1000"
```

A healthy report returns:

```json
{
  "status": "reconciled",
  "healthy": true,
  "issue_count": 0,
  "settlements_without_allocation": 0
}
```

Any `reconciliation_failed` result must block financial release automation
until investigated.

## Migrating existing settlements

Always generate a plan first:

```bash
curl -X POST \
  -H "x-api-key: $IAT_ADMIN_API_KEY" \
  "http://localhost:8000/admin/ledger/backfill-settlements?dry_run=true&limit=1000"
```

The dry run validates every split and writes nothing. Do not apply the backfill
if `error_count` is non-zero.

Apply a validated batch:

```bash
curl -X POST \
  -H "x-api-key: $IAT_ADMIN_API_KEY" \
  "http://localhost:8000/admin/ledger/backfill-settlements?dry_run=false&limit=1000"
```

The applied batch is atomic: if one candidate fails, all journals in the batch
are rolled back. Run reconciliation immediately afterward.

## Inspecting a journal

```bash
curl \
  -H "x-api-key: $IAT_ADMIN_API_KEY" \
  "http://localhost:8000/admin/ledger/transactions/ldg_tx_IDENTIFIER"
```

The response includes ordered entries and a freshly computed balance
invariant. Administrative responses never contain signing keys.

## Incident procedure

If reconciliation fails:

1. stop automated releases;
2. preserve the database and application logs;
3. run reconciliation with a bounded batch;
4. inspect every reported transaction and settlement;
5. compare ledger minor units with settlement minor units;
6. verify relevant blockchain signatures independently;
7. correct data only through a reviewed migration;
8. rerun reconciliation;
9. document the cause and prevention in a postmortem.

Never edit ledger entries manually in production.

## Remaining financial work

This version covers settlement allocation, not the complete accounting
lifecycle. Subsequent versions must add:

- verified buyer-fund receipt journals;
- escrow asset and treasury asset accounts;
- release, refund, dispute and reversal journals;
- on-chain balance reconciliation;
- period closing and immutable exports;
- independent audit tooling;
- external security and accounting review.
