import time

import pytest
from solders.keypair import Keypair

from iat.api import db, protocol_evidence
from iat.action_engine.adapters.settlement_atomic import (
    execute_settlement_atomic_action,
)
from iat.transfer import send_iat_split_atomic


def _insert_settlement_and_permit(settlement_id: str, permit_id: str) -> None:
    db.init_settlements_table()
    protocol_evidence.init_protocol_evidence_db()
    now = int(time.time())
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """INSERT INTO settlements (
                settlement_id, order_id, gross_amount_minor,
                protocol_commission_amount_minor, seller_payout_amount_minor,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (settlement_id, "order_guard", 100, 10, 90, now, now),
        )
        cursor.execute(
            """INSERT INTO protocol_settlement_execution_permits (
                permit_id, simulation_id, authorization_id, plan_id,
                settlement_id, order_id, cluster, genesis_hash, mint,
                unsigned_transaction_sha256, gross_amount_minor,
                protocol_commission_amount_minor, seller_payout_amount_minor,
                state, policy_version, permit_sha256, issued_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                permit_id, "simulation_guard", "authorization_guard", "plan_guard",
                settlement_id, "order_guard", "solana-devnet", "genesis", "mint",
                "a" * 64, 100, 10, 90, "issued", "permit_v1", "b" * 64,
                now, now + 300,
            ),
        )
        connection.commit()
    finally:
        db.release_conn(connection)


def test_permit_and_financial_execution_are_claimed_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "guard.sqlite3")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    monkeypatch.setattr(db, "pool", None)
    _insert_settlement_and_permit("settlement_guard", "pep_guard")

    claimed = db.claim_settlement_execution_db(
        "settlement_guard", execution_permit_id="pep_guard"
    )
    repeated = db.claim_settlement_execution_db(
        "settlement_guard", execution_permit_id="pep_guard"
    )

    assert claimed["broadcast_allowed"] is True
    assert claimed["execution_permit"]["permit_id"] == "pep_guard"
    assert claimed["execution_permit"]["claim_id"].startswith("pec_")
    assert repeated["broadcast_allowed"] is False

    connection = db.get_conn()
    try:
        permit = connection.cursor().execute(
            "SELECT state, claim_id FROM protocol_settlement_execution_permits"
        ).fetchone()
        settlement = connection.cursor().execute(
            "SELECT execution_claim_status FROM settlements"
        ).fetchone()
    finally:
        db.release_conn(connection)
    assert dict(permit)["state"] == "claimed"
    assert dict(permit)["claim_id"].startswith("pec_")
    assert dict(settlement)["execution_claim_status"] == "claimed"


def test_mismatched_permit_leaves_both_records_unclaimed(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "guard_mismatch.sqlite3")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    monkeypatch.setattr(db, "pool", None)
    _insert_settlement_and_permit("settlement_guard", "pep_guard")
    connection = db.get_conn()
    try:
        connection.cursor().execute(
            "UPDATE protocol_settlement_execution_permits "
            "SET seller_payout_amount_minor = 89 WHERE permit_id = ?",
            ("pep_guard",),
        )
        connection.commit()
    finally:
        db.release_conn(connection)

    blocked = db.claim_settlement_execution_db(
        "settlement_guard", execution_permit_id="pep_guard"
    )
    assert blocked["reason"] == "settlement_execution_permit_mismatch"

    connection = db.get_conn()
    try:
        permit = connection.cursor().execute(
            "SELECT state FROM protocol_settlement_execution_permits"
        ).fetchone()
        settlement = connection.cursor().execute(
            "SELECT execution_claim_status FROM settlements"
        ).fetchone()
    finally:
        db.release_conn(connection)
    assert dict(permit)["state"] == "issued"
    assert dict(settlement)["execution_claim_status"] == "unclaimed"


def test_onchain_adapter_refuses_execution_without_canonical_permit(monkeypatch):
    monkeypatch.setenv("IAT_ENABLE_ONCHAIN_SETTLEMENT", "true")
    monkeypatch.setenv("IAT_ESCROW_WALLET", str(Keypair().pubkey()))
    monkeypatch.setenv("IAT_SETTLEMENT_WALLET_SIDECAR_URL", "http://127.0.0.1:8787")
    monkeypatch.setenv("IAT_SETTLEMENT_WALLET_SIDECAR_TOKEN", "sidecar-token-long-enough")
    result = execute_settlement_atomic_action(
        {
            "action_type": "settlement_release",
            "action_scope": "financial_settlement",
            "payload": {
                "settlement_id": "settlement_guard",
                "order_id": "order_guard",
                "treasury_wallet": "treasury",
                "winner_wallet": "winner",
                "protocol_commission_amount_iat": 0.1,
                "seller_payout_amount_iat": 0.9,
                "onchain_settlement_enabled": True,
            },
        }
    )
    assert result["status"] == "action_blocked"
    assert result["reason"] == "settlement_execution_permit_required"
    assert result["result"]["broadcast_performed"] is False


def test_isolated_settlement_refuses_mainnet_before_rpc_or_sidecar(monkeypatch):
    monkeypatch.setenv("IAT_SETTLEMENT_SIMULATION_RPC_URL", "https://api.mainnet-beta.solana.com")
    with pytest.raises(RuntimeError, match="mainnet_settlement_execution_not_allowed"):
        send_iat_split_atomic(
            escrow_wallet=str(Keypair().pubkey()),
            sidecar_url="https://sidecar.example",
            sidecar_token="sidecar-token-long-enough",
            treasury_address=str(Keypair().pubkey()),
            winner_address=str(Keypair().pubkey()),
            commission_amount=0.1,
            seller_payout_amount=0.9,
            settlement_id="settlement_guard",
            order_id="order_guard",
            execution_permit={},
        )


def test_ready_for_release_waits_without_canonical_permit(monkeypatch):
    monkeypatch.setattr(
        db,
        "get_active_settlement_execution_permit_db",
        lambda _settlement_id: None,
    )

    decision = db._settlement_workflow_ready_for_release_handler(
        {"settlement_id": "settlement_guard"}
    )

    assert decision["next_status"] is None
    assert decision["decision"] == "wait_for_execution_permit"
    assert decision["broadcast_performed"] is False


def test_ready_for_release_passes_exact_permit_to_atomic_adapter(monkeypatch):
    from iat.action_engine import executor

    captured = {}
    monkeypatch.setattr(
        db,
        "get_active_settlement_execution_permit_db",
        lambda _settlement_id: {"permit_id": "pep_exact"},
    )

    def execute_action(**kwargs):
        captured.update(kwargs)
        return {
            "status": "action_blocked",
            "reason": "test_no_broadcast",
            "result": {},
        }

    monkeypatch.setattr(executor, "execute_action", execute_action)
    monkeypatch.setattr(
        db,
        "update_settlement_payload_db",
        lambda **_kwargs: {"status": "test_payload_not_persisted"},
    )

    decision = db._settlement_workflow_ready_for_release_handler(
        {
            "settlement_id": "settlement_guard",
            "order_id": "order_guard",
            "winner_wallet": str(Keypair().pubkey()),
            "treasury_wallet": str(Keypair().pubkey()),
            "gross_amount_iat": 1.5,
            "protocol_commission_amount_iat": 0.15,
            "seller_payout_amount_iat": 1.35,
        }
    )

    assert captured["payload"]["execution_permit_id"] == "pep_exact"
    assert captured["payload"]["onchain_settlement_enabled"] is True
    assert decision["next_status"] == "release_failed"


def test_active_permit_lookup_rejects_expired_and_other_settlement(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "permit_lookup.sqlite3")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    monkeypatch.setattr(db, "pool", None)
    _insert_settlement_and_permit("settlement_guard", "pep_guard")

    assert db.get_active_settlement_execution_permit_db("other_settlement") is None

    connection = db.get_conn()
    try:
        connection.cursor().execute(
            "UPDATE protocol_settlement_execution_permits SET expires_at = ?",
            (int(time.time()) - 1,),
        )
        connection.commit()
    finally:
        db.release_conn(connection)

    assert db.get_active_settlement_execution_permit_db("settlement_guard") is None
