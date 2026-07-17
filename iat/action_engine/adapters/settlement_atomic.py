import os

from iat.action_engine.models import build_action_result
from iat.transfer import send_iat_split_atomic


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

    escrow_keypair_path = (
        os.getenv("IAT_ESCROW_KEYPAIR_JSON")
        or os.getenv("IAT_ESCROW_KEYPAIR_PATH")
    )

    if not escrow_keypair_path:
        return build_action_result(
            status="action_blocked",
            action_type=action_type,
            action_scope=action_scope,
            reason="escrow_keypair_path_missing",
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
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

    try:
        atomic_signature = send_iat_split_atomic(
            from_keypair_path=escrow_keypair_path,
            treasury_address=treasury_wallet,
            winner_address=winner_wallet,
            commission_amount=commission_amount,
            seller_payout_amount=seller_payout_amount,
            memo_text=f"IAT_SETTLEMENT:{settlement_id}:{order_id}",
        )

        if not atomic_signature:
            return build_action_result(
                status="action_failed",
                action_type=action_type,
                action_scope=action_scope,
                reason="atomic_transaction_signature_missing",
                result={
                    "settlement_id": settlement_id,
                    "order_id": order_id,
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
            },
        )

    except Exception as exc:
        return build_action_result(
            status="action_failed",
            action_type=action_type,
            action_scope=action_scope,
            reason="atomic_settlement_transaction_failed",
            error=str(exc),
            result={
                "settlement_id": settlement_id,
                "order_id": order_id,
            },
        )
