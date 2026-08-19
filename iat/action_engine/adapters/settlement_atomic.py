import os

from iat.action_engine.models import build_action_result
from iat.transfer import send_iat_split_atomic
from iat.api.db import (
    claim_settlement_execution_db,
    mark_settlement_execution_error_db,
    record_settlement_broadcast_db,
)


def execute_settlement_atomic_action(action_request):
    """
    Execute protocol commission and seller payout in one atomic Solana
    transaction.

    Both transfers share one transaction signature because they are separate
    instructions inside the same atomic transaction.
    """
    action_request = action_request or {}
    payload = action_request.get("payload") or {}

    action_type = action_request.get("action_type", "settlement_release")
    action_scope = action_request.get("action_scope", "financial_settlement")

    settlement_id = payload.get("settlement_id")
    order_id = payload.get("order_id")
    treasury_wallet = payload.get("treasury_wallet")
    winner_wallet = payload.get("winner_wallet")

    try:
        commission_amount = float(
            payload.get("protocol_commission_amount_iat") or 0
        )
        seller_payout_amount = float(
            payload.get("seller_payout_amount_iat") or 0
        )
    except (TypeError, ValueError) as exc:
        return build_action_result(
            status="action_failed",
            action_type=action_type,
            action_scope=action_scope,
            reason="invalid_settlement_amount",
            error=str(exc),
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
            },
        )

    onchain_enabled = (
        str(os.getenv("IAT_ENABLE_ONCHAIN_SETTLEMENT", "false")).lower()
        == "true"
    )

    payload_onchain_enabled = (
        payload.get("onchain_settlement_enabled") is True
    )

    if not onchain_enabled or not payload_onchain_enabled:
        return build_action_result(
            status="action_blocked",
            action_type=action_type,
            action_scope=action_scope,
            reason="onchain_settlement_not_enabled",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
                "environment_enabled": onchain_enabled,
                "payload_enabled": payload_onchain_enabled,
            },
        )

    escrow_wallet = os.getenv("IAT_ESCROW_WALLET", "").strip()
    sidecar_url = os.getenv(
        "IAT_SETTLEMENT_WALLET_SIDECAR_URL",
        "http://127.0.0.1:10000/internal/settlement-wallet",
    ).strip()
    sidecar_token = os.getenv("IAT_SETTLEMENT_WALLET_SIDECAR_TOKEN", "")
    if not escrow_wallet or not sidecar_url or len(sidecar_token) < 16:
        return build_action_result(
            status="action_blocked",
            action_type=action_type,
            action_scope=action_scope,
            reason="isolated_settlement_sidecar_not_configured",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
                "private_key_required_by_api": False,
            },
        )

    if not treasury_wallet:
        return build_action_result(
            status="action_blocked",
            action_type=action_type,
            action_scope=action_scope,
            reason="treasury_wallet_missing",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
            },
        )

    if not winner_wallet:
        return build_action_result(
            status="action_blocked",
            action_type=action_type,
            action_scope=action_scope,
            reason="winner_wallet_missing",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
            },
        )

    if commission_amount < 0 or seller_payout_amount < 0:
        return build_action_result(
            status="action_blocked",
            action_type=action_type,
            action_scope=action_scope,
            reason="negative_settlement_amount",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
                "commission_amount_iat": commission_amount,
                "seller_payout_amount_iat": seller_payout_amount,
            },
        )

    if commission_amount + seller_payout_amount <= 0:
        return build_action_result(
            status="action_blocked",
            action_type=action_type,
            action_scope=action_scope,
            reason="settlement_total_amount_must_be_positive",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
            },
        )

    execution_permit_id = (
        payload.get("execution_permit_id") or payload.get("permit_id")
    )
    if not execution_permit_id:
        return build_action_result(
            status="action_blocked",
            action_type=action_type,
            action_scope=action_scope,
            reason="settlement_execution_permit_required",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
                "broadcast_performed": False,
                "execution_guard": "settlement_execution_guard_v2",
            },
        )

    claim_result = claim_settlement_execution_db(
        settlement_id=settlement_id,
        execution_permit_id=execution_permit_id,
    )

    if claim_result.get("status") == "settlement_already_submitted":
        existing_signature = claim_result.get(
            "atomic_tx_signature"
        )

        return build_action_result(
            status="settlement_release_submitted",
            action_type=action_type,
            action_scope=action_scope,
            reason="atomic_settlement_idempotent_existing_submission",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
                "execution_mode": "onchain_atomic",
                "broadcast_performed": False,
                "idempotent": True,
                "atomic_tx_signature": existing_signature,
                "commission_tx_signature": (
                    claim_result.get("commission_tx_signature")
                    or existing_signature
                ),
                "seller_payout_tx_signature": (
                    claim_result.get("seller_payout_tx_signature")
                    or existing_signature
                ),
                "execution_guard": claim_result,
            },
        )

    if not claim_result.get("broadcast_allowed"):
        return build_action_result(
            status="action_blocked",
            action_type=action_type,
            action_scope=action_scope,
            reason=(
                claim_result.get("reason")
                or "settlement_execution_claim_not_acquired"
            ),
            error=claim_result.get("error"),
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
                "broadcast_performed": False,
                "idempotent": bool(
                    claim_result.get("idempotent")
                ),
                "execution_guard": claim_result,
            },
        )

    claim_token = claim_result.get("claim_token")

    try:
        atomic_signature = send_iat_split_atomic(
            escrow_wallet=escrow_wallet,
            sidecar_url=sidecar_url,
            sidecar_token=sidecar_token,
            treasury_address=treasury_wallet,
            winner_address=winner_wallet,
            commission_amount=commission_amount,
            seller_payout_amount=seller_payout_amount,
            settlement_id=settlement_id,
            order_id=order_id,
            execution_permit=claim_result.get("execution_permit"),
            memo_text=f"IAT_SETTLEMENT:{settlement_id}:{order_id}",
        )

        if not atomic_signature:
            error_record = mark_settlement_execution_error_db(
                settlement_id=settlement_id,
                claim_token=claim_token,
                error="atomic_transaction_signature_missing",
                broadcast_state="unknown",
            )

            return build_action_result(
                status="action_failed",
                action_type=action_type,
                action_scope=action_scope,
                reason="atomic_transaction_signature_missing",
                result={
                    "settlement_id": settlement_id,
                    "order_id": order_id,
                    "broadcast_performed": None,
                    "broadcast_state": "unknown",
                    "execution_claim_token": claim_token,
                    "execution_guard": claim_result,
                    "execution_error_record": error_record,
                    "automatic_retry_allowed": False,
                },
            )

        broadcast_record = record_settlement_broadcast_db(
            settlement_id=settlement_id,
            claim_token=claim_token,
            atomic_tx_signature=atomic_signature,
        )

        if not broadcast_record.get("recorded"):
            persistence_error_record = (
                mark_settlement_execution_error_db(
                    settlement_id=settlement_id,
                    claim_token=claim_token,
                    error=(
                        broadcast_record.get("error")
                        or broadcast_record.get("reason")
                        or "atomic_signature_persistence_failed"
                    ),
                    broadcast_state="unknown",
                )
            )

            return build_action_result(
                status="action_failed",
                action_type=action_type,
                action_scope=action_scope,
                reason="atomic_signature_persistence_failed",
                error=broadcast_record.get("error"),
                result={
                    "settlement_id": settlement_id,
                    "order_id": order_id,
                    "atomic_tx_signature": atomic_signature,
                    "commission_tx_signature": atomic_signature,
                    "seller_payout_tx_signature": atomic_signature,
                    "broadcast_performed": True,
                    "broadcast_state": "submitted_unpersisted",
                    "signature_persisted": False,
                    "automatic_retry_allowed": False,
                    "execution_claim_token": claim_token,
                    "execution_guard": claim_result,
                    "broadcast_record": broadcast_record,
                    "execution_error_record": (
                        persistence_error_record
                    ),
                },
            )

        return build_action_result(
            status="settlement_release_submitted",
            action_type=action_type,
            action_scope=action_scope,
            reason="atomic_settlement_transaction_submitted",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
                "execution_mode": "onchain_atomic",
                "atomic_tx_signature": atomic_signature,
                "commission_tx_signature": atomic_signature,
                "seller_payout_tx_signature": atomic_signature,
                "commission_amount_iat": commission_amount,
                "seller_payout_amount_iat": seller_payout_amount,
                "treasury_wallet": treasury_wallet,
                "winner_wallet": winner_wallet,
                "broadcast_performed": True,
                "idempotent": False,
                "execution_claim_token": claim_token,
                "execution_guard": claim_result,
                "broadcast_record": broadcast_record,
                "signature_persisted": bool(
                    broadcast_record.get("recorded")
                ),
            },
        )

    except Exception as exc:
        error_record = mark_settlement_execution_error_db(
            settlement_id=settlement_id,
            claim_token=claim_token,
            error=str(exc),
            broadcast_state="unknown",
        )
        return build_action_result(
            status="action_failed",
            action_type=action_type,
            action_scope=action_scope,
            reason="atomic_settlement_transaction_failed",
            error=str(exc),
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
                "broadcast_performed": None,
                "broadcast_state": "unknown",
                "execution_claim_token": claim_token,
                "execution_guard": claim_result,
                "execution_error_record": error_record,
                "automatic_retry_allowed": False,
            },
        )
