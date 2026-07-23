import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from iat.api import db
from iat.api.ledger_db import (
    backfill_settlement_allocations,
    get_ledger_transaction,
    reconcile_ledger,
)
from iat.ledger import (
    LedgerValidationError,
    build_settlement_allocation_journal,
    iat_to_minor,
    minor_to_iat,
    validate_journal,
)


@pytest.fixture()
def ledger_database(tmp_path, monkeypatch):
    database = tmp_path / "ledger.sqlite"
    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    db.init_db()
    return database


def _settlement():
    return {
        "winner_id": "seller-001",
        "winner_wallet": "seller-wallet",
        "protocol_treasury_wallet": "treasury-wallet",
        "gross_amount_iat": "1.00000003",
        "protocol_commission_rate": "0.10",
        "protocol_commission_amount_iat": "0.10000001",
        "seller_payout_amount_iat": "0.90000002",
        "winner_payment_status": "created",
    }


def test_iat_amounts_use_exact_integer_minor_units():
    assert iat_to_minor("1.00000003") == 100_000_003
    assert minor_to_iat(100_000_003) == "1.00000003"
    assert iat_to_minor("0.000000005") == 1


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1"])
def test_iat_amount_rejects_unsafe_values(value):
    with pytest.raises(LedgerValidationError):
        iat_to_minor(value)


def test_journal_must_balance_per_currency():
    with pytest.raises(LedgerValidationError, match="journal_not_balanced"):
        validate_journal(
            [
                {
                    "account_id": "debit",
                    "direction": "debit",
                    "amount_minor": 100,
                    "currency": "IAT",
                },
                {
                    "account_id": "credit",
                    "direction": "credit",
                    "amount_minor": 99,
                    "currency": "IAT",
                },
            ]
        )


def test_settlement_split_must_equal_gross():
    with pytest.raises(LedgerValidationError, match="split_does_not_equal_gross"):
        build_settlement_allocation_journal(
            settlement_id="settlement-invalid",
            gross_amount_iat="1.00",
            protocol_commission_amount_iat="0.10",
            seller_payout_amount_iat="0.89",
            seller_id="seller-001",
        )


def test_settlement_and_ledger_commit_atomically(ledger_database):
    result = db.record_settlement_db("order-ledger-001", _settlement())

    assert result["status"] == "settlement_recorded"
    assert result["ledger"]["status"] == "posted"
    transaction = get_ledger_transaction(result["ledger"]["transaction_id"])
    assert transaction["invariant"]["status"] == "balanced"
    assert sum(
        entry["amount_minor"]
        for entry in transaction["entries"]
        if entry["direction"] == "debit"
    ) == 100_000_003

    connection = sqlite3.connect(ledger_database)
    stored = connection.execute(
        """
        SELECT gross_amount_minor, protocol_commission_amount_minor,
               seller_payout_amount_minor
        FROM settlements
        WHERE order_id = ?
        """,
        ("order-ledger-001",),
    ).fetchone()
    connection.close()
    assert stored == (100_000_003, 10_000_001, 90_000_002)


def test_invalid_journal_rolls_back_settlement_and_ledger(ledger_database):
    invalid = _settlement()
    invalid["seller_payout_amount_iat"] = "0.80"

    with pytest.raises(LedgerValidationError):
        db.record_settlement_db("order-invalid", invalid)

    connection = sqlite3.connect(ledger_database)
    settlement_count = connection.execute(
        "SELECT COUNT(*) FROM settlements WHERE order_id = ?",
        ("order-invalid",),
    ).fetchone()[0]
    ledger_count = connection.execute(
        "SELECT COUNT(*) FROM ledger_transactions WHERE order_id = ?",
        ("order-invalid",),
    ).fetchone()[0]
    connection.close()
    assert settlement_count == 0
    assert ledger_count == 0


def test_repeated_settlement_is_idempotent(ledger_database):
    first = db.record_settlement_db("order-idempotent", _settlement())
    second = db.record_settlement_db("order-idempotent", _settlement())

    assert first["status"] == "settlement_recorded"
    assert second["status"] == "settlement_already_recorded"
    assert second["idempotent"] is True

    connection = sqlite3.connect(ledger_database)
    settlement_count = connection.execute(
        "SELECT COUNT(*) FROM settlements WHERE order_id = ?",
        ("order-idempotent",),
    ).fetchone()[0]
    ledger_count = connection.execute(
        "SELECT COUNT(*) FROM ledger_transactions WHERE order_id = ?",
        ("order-idempotent",),
    ).fetchone()[0]
    connection.close()
    assert settlement_count == 1
    assert ledger_count == 1


def test_concurrent_settlement_creation_has_one_winner(ledger_database):
    def create():
        return db.record_settlement_db("order-concurrent", _settlement())

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: create(), range(8)))

    assert sum(result["status"] == "settlement_recorded" for result in results) == 1
    assert sum(result["status"] == "settlement_already_recorded" for result in results) == 7

    connection = sqlite3.connect(ledger_database)
    assert connection.execute(
        "SELECT COUNT(*) FROM settlements WHERE order_id = 'order-concurrent'"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM ledger_transactions WHERE order_id = 'order-concurrent'"
    ).fetchone()[0] == 1
    connection.close()


def test_reconciliation_detects_no_issue_for_valid_ledger(ledger_database):
    db.record_settlement_db("order-reconcile", _settlement())

    report = reconcile_ledger()

    assert report["status"] == "reconciled"
    assert report["healthy"] is True
    assert report["transactions_checked"] == 1
    assert report["issue_count"] == 0


def test_reconciliation_detects_tampered_entry(ledger_database):
    result = db.record_settlement_db("order-tampered", _settlement())
    transaction_id = result["ledger"]["transaction_id"]
    connection = sqlite3.connect(ledger_database)
    connection.execute(
        """
        UPDATE ledger_entries
        SET amount_minor = amount_minor + 1
        WHERE transaction_id = ? AND direction = 'credit'
        """,
        (transaction_id,),
    )
    connection.commit()
    connection.close()

    report = reconcile_ledger()

    assert report["status"] == "reconciliation_failed"
    assert report["healthy"] is False
    assert report["issues"][0]["type"] == "unbalanced_journal"


def test_reconciliation_detects_and_backfills_legacy_settlement(ledger_database):
    result = db.record_settlement_db("order-legacy", _settlement())
    transaction_id = result["ledger"]["transaction_id"]
    connection = sqlite3.connect(ledger_database)
    connection.execute(
        "DELETE FROM ledger_entries WHERE transaction_id = ?",
        (transaction_id,),
    )
    connection.execute(
        "DELETE FROM ledger_transactions WHERE transaction_id = ?",
        (transaction_id,),
    )
    connection.commit()
    connection.close()

    missing = reconcile_ledger()
    plan = backfill_settlement_allocations(dry_run=True)
    applied = backfill_settlement_allocations(dry_run=False)
    healthy = reconcile_ledger()

    assert missing["settlements_without_allocation"] == 1
    assert missing["issues"][0]["type"] == "ledger_allocation_missing"
    assert plan["status"] == "backfill_plan_ready"
    assert plan["posted_count"] == 0
    assert applied["status"] == "backfill_completed"
    assert applied["posted_count"] == 1
    assert healthy["healthy"] is True


def test_state_transition_is_versioned_and_compare_and_swap_safe(ledger_database):
    settlement = db.record_settlement_db("order-state", _settlement())
    settlement_id = settlement["settlement_id"]

    def authorize():
        return db.update_settlement_status_db(
            settlement_id,
            "authorized",
            reason="concurrent_authorization_test",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: authorize(), range(4)))

    assert sum(result["status"] == "settlement_status_updated" for result in results) == 1
    assert all(
        result["status"] in {
            "settlement_status_updated",
            "transition_conflict",
            "transition_rejected",
        }
        for result in results
    )
    stored = db.get_settlement_by_order_id_db("order-state")
    assert stored["settlement_status"] == "authorized"
    assert stored["settlement_payload"]["state_machine_version"] == "settlement_state_machine_v2"
