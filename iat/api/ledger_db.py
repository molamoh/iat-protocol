"""Persistent double-entry ledger using the protocol database connection."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from iat.ledger import (
    LEDGER_VERSION,
    LedgerValidationError,
    build_settlement_allocation_journal,
    minor_to_iat,
    validate_journal,
)


def init_ledger_tables() -> None:
    from iat.api import db

    conn = db.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_accounts (
                account_id TEXT PRIMARY KEY,
                account_type TEXT NOT NULL,
                owner_id TEXT,
                currency TEXT NOT NULL,
                normal_balance TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_transactions (
                transaction_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                settlement_id TEXT,
                order_id TEXT,
                event_type TEXT NOT NULL,
                transaction_status TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_entries (
                entry_id TEXT PRIMARY KEY,
                transaction_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                account_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                amount_minor BIGINT NOT NULL,
                currency TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(transaction_id, sequence_number)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ledger_entries_transaction
            ON ledger_entries(transaction_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ledger_transactions_settlement
            ON ledger_transactions(settlement_id)
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db.release_conn(conn)


def post_settlement_allocation_conn(
    conn,
    *,
    settlement_id: str,
    order_id: str,
    seller_id: str | None,
    gross_amount_iat: Any,
    protocol_commission_amount_iat: Any,
    seller_payout_amount_iat: Any,
) -> dict[str, Any]:
    """Post an allocation using the caller's transaction."""
    from iat.api import db

    journal = build_settlement_allocation_journal(
        settlement_id=settlement_id,
        gross_amount_iat=gross_amount_iat,
        protocol_commission_amount_iat=protocol_commission_amount_iat,
        seller_payout_amount_iat=seller_payout_amount_iat,
        seller_id=seller_id,
    )
    cur = conn.cursor()
    p = db.qmark()
    cur.execute(
        f"""
        SELECT transaction_id, payload_hash
        FROM ledger_transactions
        WHERE idempotency_key = {p}
        """,
        (journal["idempotency_key"],),
    )
    existing = cur.fetchone()
    if existing:
        existing = dict(existing)
        if existing.get("payload_hash") != journal["payload_hash"]:
            raise LedgerValidationError("ledger_idempotency_payload_conflict")
        return {
            "status": "already_posted",
            "transaction_id": existing.get("transaction_id"),
            "idempotent": True,
        }

    transaction_id = f"ldg_tx_{uuid.uuid4()}"
    now = int(time.time())
    metadata = {
        "ledger_version": LEDGER_VERSION,
        "journal_payload": journal["payload"],
        "invariant": journal["invariant"],
    }
    cur.execute(
        f"""
        INSERT INTO ledger_transactions (
            transaction_id, idempotency_key, settlement_id, order_id,
            event_type, transaction_status, payload_hash, metadata_json, created_at
        )
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """,
        (
            transaction_id,
            journal["idempotency_key"],
            settlement_id,
            order_id,
            journal["event_type"],
            "posted",
            journal["payload_hash"],
            json.dumps(metadata, sort_keys=True),
            now,
        ),
    )
    for sequence, entry in enumerate(journal["entries"], start=1):
        _ensure_account_conn(cur, entry["account_id"], seller_id, now, p)
        cur.execute(
            f"""
            INSERT INTO ledger_entries (
                entry_id, transaction_id, sequence_number, account_id,
                direction, amount_minor, currency, created_at
            )
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """,
            (
                f"ldg_ent_{uuid.uuid4()}",
                transaction_id,
                sequence,
                entry["account_id"],
                entry["direction"],
                entry["amount_minor"],
                entry["currency"],
                now,
            ),
        )
    return {
        "status": "posted",
        "transaction_id": transaction_id,
        "idempotent": False,
        "invariant": journal["invariant"],
    }


def get_ledger_transaction(transaction_id: str) -> dict[str, Any] | None:
    from iat.api import db

    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"SELECT * FROM ledger_transactions WHERE transaction_id = {p}",
            (transaction_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        transaction = dict(row)
        cur.execute(
            f"""
            SELECT sequence_number, account_id, direction, amount_minor, currency
            FROM ledger_entries
            WHERE transaction_id = {p}
            ORDER BY sequence_number
            """,
            (transaction_id,),
        )
        transaction["entries"] = [dict(entry) for entry in cur.fetchall()]
        transaction["invariant"] = validate_journal(transaction["entries"])
        transaction["metadata"] = json.loads(transaction.pop("metadata_json") or "{}")
        return transaction
    finally:
        db.release_conn(conn)


def reconcile_ledger(limit: int = 1000) -> dict[str, Any]:
    from iat.api import db

    bounded_limit = max(1, min(int(limit), 10_000))
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"""
            SELECT transaction_id, settlement_id, order_id, event_type, payload_hash
            FROM ledger_transactions
            WHERE transaction_status = 'posted'
            ORDER BY created_at DESC
            LIMIT {p}
            """,
            (bounded_limit,),
        )
        transactions = [dict(row) for row in cur.fetchall()]
        issues = []
        checked_entries = 0
        for transaction in transactions:
            cur.execute(
                f"""
                SELECT account_id, direction, amount_minor, currency
                FROM ledger_entries
                WHERE transaction_id = {p}
                ORDER BY sequence_number
                """,
                (transaction["transaction_id"],),
            )
            entries = [dict(row) for row in cur.fetchall()]
            checked_entries += len(entries)
            try:
                validate_journal(entries)
            except LedgerValidationError as exc:
                issues.append(
                    {
                        "type": "unbalanced_journal",
                        "transaction_id": transaction["transaction_id"],
                        "reason": str(exc),
                    }
                )
                continue
            if transaction["event_type"] == "settlement_allocated":
                issue = _reconcile_settlement_conn(cur, transaction, entries, p)
                if issue:
                    issues.append(issue)
        cur.execute(
            f"""
            SELECT s.settlement_id, s.order_id
            FROM settlements s
            LEFT JOIN ledger_transactions lt
              ON lt.settlement_id = s.settlement_id
             AND lt.event_type = 'settlement_allocated'
            WHERE lt.transaction_id IS NULL
            ORDER BY s.created_at DESC
            LIMIT {p}
            """,
            (bounded_limit,),
        )
        missing_allocations = [dict(row) for row in cur.fetchall()]
        for missing in missing_allocations:
            issues.append(
                {
                    "type": "ledger_allocation_missing",
                    "settlement_id": missing["settlement_id"],
                    "order_id": missing["order_id"],
                }
            )
        return {
            "status": "reconciled" if not issues else "reconciliation_failed",
            "ledger": LEDGER_VERSION,
            "transactions_checked": len(transactions),
            "entries_checked": checked_entries,
            "settlements_without_allocation": len(missing_allocations),
            "issue_count": len(issues),
            "issues": issues,
            "healthy": not issues,
        }
    finally:
        db.release_conn(conn)


def backfill_settlement_allocations(
    *,
    dry_run: bool = True,
    limit: int = 1000,
) -> dict[str, Any]:
    """Plan or apply ledger allocations for legacy settlements."""
    from iat.api import db

    bounded_limit = max(1, min(int(limit), 10_000))
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        p = db.qmark()
        cur.execute(
            f"""
            SELECT s.*
            FROM settlements s
            LEFT JOIN ledger_transactions lt
              ON lt.settlement_id = s.settlement_id
             AND lt.event_type = 'settlement_allocated'
            WHERE lt.transaction_id IS NULL
            ORDER BY s.created_at
            LIMIT {p}
            """,
            (bounded_limit,),
        )
        candidates = [dict(row) for row in cur.fetchall()]
        planned = []
        errors = []
        posted = []
        for settlement in candidates:
            try:
                journal = build_settlement_allocation_journal(
                    settlement_id=settlement["settlement_id"],
                    gross_amount_iat=settlement.get("gross_amount_iat", 0),
                    protocol_commission_amount_iat=settlement.get(
                        "protocol_commission_amount_iat", 0
                    ),
                    seller_payout_amount_iat=settlement.get("seller_payout_amount_iat", 0),
                    seller_id=settlement.get("winner_id"),
                )
                planned.append(
                    {
                        "settlement_id": settlement["settlement_id"],
                        "order_id": settlement["order_id"],
                        "payload_hash": journal["payload_hash"],
                        "balanced": True,
                    }
                )
                if not dry_run:
                    result = post_settlement_allocation_conn(
                        conn,
                        settlement_id=settlement["settlement_id"],
                        order_id=settlement["order_id"],
                        seller_id=settlement.get("winner_id"),
                        gross_amount_iat=settlement.get("gross_amount_iat", 0),
                        protocol_commission_amount_iat=settlement.get(
                            "protocol_commission_amount_iat", 0
                        ),
                        seller_payout_amount_iat=settlement.get(
                            "seller_payout_amount_iat", 0
                        ),
                    )
                    posted.append(
                        {
                            "settlement_id": settlement["settlement_id"],
                            "transaction_id": result.get("transaction_id"),
                            "status": result.get("status"),
                        }
                    )
            except Exception as exc:
                errors.append(
                    {
                        "settlement_id": settlement.get("settlement_id"),
                        "order_id": settlement.get("order_id"),
                        "reason": str(exc),
                    }
                )
        if dry_run:
            conn.rollback()
        elif errors:
            conn.rollback()
            posted = []
        else:
            conn.commit()
        return {
            "status": (
                "backfill_plan_ready"
                if dry_run and not errors
                else "backfill_completed"
                if not dry_run and not errors
                else "backfill_validation_failed"
            ),
            "dry_run": bool(dry_run),
            "candidate_count": len(candidates),
            "planned_count": len(planned),
            "posted_count": len(posted),
            "error_count": len(errors),
            "planned": planned,
            "posted": posted,
            "errors": errors,
            "atomic_apply": not dry_run,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        db.release_conn(conn)


def _ensure_account_conn(cur, account_id: str, seller_id: str | None, now: int, p: str) -> None:
    account_type = "clearing"
    owner_id = None
    normal_balance = "debit"
    if account_id.startswith("iat:seller_payable:"):
        account_type = "liability"
        owner_id = seller_id
        normal_balance = "credit"
    elif account_id == "iat:protocol_commission_revenue":
        account_type = "revenue"
        owner_id = "iat_protocol"
        normal_balance = "credit"

    from iat.api import db

    sql = db.sql_insert_ignore(
        "ledger_accounts",
        [
            "account_id",
            "account_type",
            "owner_id",
            "currency",
            "normal_balance",
            "created_at",
        ],
        ["account_id"],
    )
    cur.execute(
        sql,
        (account_id, account_type, owner_id, "IAT", normal_balance, now),
    )


def _reconcile_settlement_conn(cur, transaction, entries, p: str) -> dict[str, Any] | None:
    cur.execute(
        f"""
        SELECT gross_amount_iat, protocol_commission_amount_iat, seller_payout_amount_iat
             , gross_amount_minor, protocol_commission_amount_minor, seller_payout_amount_minor
        FROM settlements
        WHERE settlement_id = {p}
        """,
        (transaction["settlement_id"],),
    )
    settlement = cur.fetchone()
    if not settlement:
        return {
            "type": "settlement_missing",
            "transaction_id": transaction["transaction_id"],
            "settlement_id": transaction["settlement_id"],
        }
    settlement = dict(settlement)
    debits = sum(entry["amount_minor"] for entry in entries if entry["direction"] == "debit")
    credits = {
        entry["account_id"]: entry["amount_minor"]
        for entry in entries
        if entry["direction"] == "credit"
    }
    from iat.ledger import iat_to_minor

    expected_gross = (
        int(settlement["gross_amount_minor"])
        if settlement.get("gross_amount_minor") is not None
        else iat_to_minor(settlement["gross_amount_iat"])
    )
    expected_commission = (
        int(settlement["protocol_commission_amount_minor"])
        if settlement.get("protocol_commission_amount_minor") is not None
        else iat_to_minor(settlement["protocol_commission_amount_iat"])
    )
    expected_payout = (
        int(settlement["seller_payout_amount_minor"])
        if settlement.get("seller_payout_amount_minor") is not None
        else iat_to_minor(settlement["seller_payout_amount_iat"])
    )
    actual_commission = credits.get("iat:protocol_commission_revenue", 0)
    actual_payout = sum(
        value for account, value in credits.items() if account.startswith("iat:seller_payable:")
    )
    if (debits, actual_commission, actual_payout) != (
        expected_gross,
        expected_commission,
        expected_payout,
    ):
        return {
            "type": "settlement_amount_mismatch",
            "transaction_id": transaction["transaction_id"],
            "settlement_id": transaction["settlement_id"],
            "expected": {
                "gross": minor_to_iat(expected_gross),
                "commission": minor_to_iat(expected_commission),
                "payout": minor_to_iat(expected_payout),
            },
            "actual": {
                "gross": minor_to_iat(debits),
                "commission": minor_to_iat(actual_commission),
                "payout": minor_to_iat(actual_payout),
            },
        }
    return None
