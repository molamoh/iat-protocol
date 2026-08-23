import time

import pytest
from solders.keypair import Keypair

from iat.settlement_signing_policy import BoundedSettlementApproval


ESCROW = str(Keypair.from_seed(bytes([21]) * 32).pubkey())
TREASURY = str(Keypair.from_seed(bytes([22]) * 32).pubkey())


def policy() -> BoundedSettlementApproval:
    return BoundedSettlementApproval(
        escrow_wallet=ESCROW,
        treasury_wallet=TREASURY,
        maximum_gross_iat_minor=1_000_000_000,
    )


def review(**changes):
    digest = "ab" * 32
    value = {
        "policy_version": "settlement_signing_policy_v1",
        "cluster": "solana:devnet",
        "fee_payer": ESCROW,
        "expires_at": int(time.time()) + 120,
        "transaction_sha256": digest,
        "settlement": {
            "asset": "IAT",
            "settlement_id": "settlement_1",
            "order_id": "order_1",
            "treasury_wallet": TREASURY,
            "gross_amount_minor": 100,
            "protocol_commission_amount_minor": 10,
            "seller_payout_amount_minor": 90,
        },
        "execution_permit": {
            "permit_id": "pep_123",
            "claim_id": "pec_123",
            "state": "claimed",
            "settlement_id": "settlement_1",
            "order_id": "order_1",
        },
        "final_simulation": {
            "status": "succeeded",
            "transaction_sha256": digest,
        },
        "simulation": {
            "status": "succeeded",
            "transaction_sha256": digest,
        },
    }
    value.update(changes)
    return value


def test_claimed_permit_and_exact_final_simulation_are_approved():
    assert policy().approve(review()) is True


@pytest.mark.parametrize(
    "change",
    [
        {"cluster": "solana:mainnet"},
        {"fee_payer": TREASURY},
        {"transaction_sha256": "cd" * 32},
        {"expires_at": 0},
        {"execution_permit": {}},
        {"final_simulation": {"status": "failed", "transaction_sha256": "ab" * 32}},
        {"simulation": {"status": "failed", "transaction_sha256": "ab" * 32}},
        {"simulation": {"status": "succeeded", "transaction_sha256": "cd" * 32}},
        {
            "settlement": {
                "asset": "IAT",
                "settlement_id": "settlement_1",
                "order_id": "order_1",
                "treasury_wallet": TREASURY,
                "gross_amount_minor": 100,
                "protocol_commission_amount_minor": 10,
                "seller_payout_amount_minor": 89,
            }
        },
    ],
)
def test_policy_fails_closed_when_any_binding_changes(change):
    assert policy().approve(review(**change)) is False


def test_policy_rejects_mainnet_configuration():
    with pytest.raises(ValueError, match="devnet_only"):
        BoundedSettlementApproval(
            escrow_wallet=ESCROW,
            treasury_wallet=TREASURY,
            maximum_gross_iat_minor=1,
            cluster="solana:mainnet",
        )
