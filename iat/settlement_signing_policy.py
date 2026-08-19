"""Bounded approval policy for isolated IAT settlement signers."""

from __future__ import annotations

import hmac
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping

from solders.pubkey import Pubkey


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class BoundedSettlementApproval:
    """Approve metadata for one exact, claimed, devnet settlement permit."""

    escrow_wallet: str
    treasury_wallet: str
    maximum_gross_iat_minor: int
    cluster: str = "solana:devnet"

    def __post_init__(self) -> None:
        try:
            Pubkey.from_string(self.escrow_wallet)
            Pubkey.from_string(self.treasury_wallet)
        except ValueError as exc:
            raise ValueError("settlement_policy_wallet_invalid") from exc
        if not 1 <= int(self.maximum_gross_iat_minor) <= 10**18:
            raise ValueError("settlement_policy_limit_out_of_bounds")
        if self.cluster != "solana:devnet":
            raise ValueError("settlement_policy_devnet_only")

    def approve(self, review: Mapping[str, Any]) -> bool:
        payment = review.get("settlement")
        permit = review.get("execution_permit")
        simulation = review.get("final_simulation")
        if not all(isinstance(value, Mapping) for value in (payment, permit, simulation)):
            return False
        try:
            gross = int(payment.get("gross_amount_minor"))
            commission = int(payment.get("protocol_commission_amount_minor"))
            payout = int(payment.get("seller_payout_amount_minor"))
            expires_at = int(review.get("expires_at"))
        except (TypeError, ValueError):
            return False
        now = int(time.time())
        transaction_sha256 = str(review.get("transaction_sha256") or "")
        simulation_sha256 = str(simulation.get("transaction_sha256") or "")
        permit_id = str(permit.get("permit_id") or "")
        claim_id = str(permit.get("claim_id") or "")
        settlement_id = str(payment.get("settlement_id") or "")
        order_id = str(payment.get("order_id") or "")
        checks = (
            review.get("policy_version") == "settlement_signing_policy_v1",
            review.get("cluster") == self.cluster,
            hmac.compare_digest(str(review.get("fee_payer") or ""), self.escrow_wallet),
            hmac.compare_digest(
                str(payment.get("treasury_wallet") or ""), self.treasury_wallet
            ),
            str(payment.get("asset") or "").upper() == "IAT",
            0 < gross <= self.maximum_gross_iat_minor,
            commission >= 0,
            payout >= 0,
            commission + payout == gross,
            bool(settlement_id),
            bool(order_id),
            permit_id.startswith("pep_"),
            claim_id.startswith("pec_"),
            permit.get("state") == "claimed",
            hmac.compare_digest(
                str(permit.get("settlement_id") or ""), settlement_id
            ),
            hmac.compare_digest(str(permit.get("order_id") or ""), order_id),
            simulation.get("status") == "succeeded",
            _SHA256.fullmatch(transaction_sha256) is not None,
            hmac.compare_digest(transaction_sha256, simulation_sha256),
            now < expires_at <= now + 300,
        )
        return all(checks)
