"""Local, non-custodial buyer runner for one bounded IAT lifecycle step."""

from __future__ import annotations

import base64
import hmac
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import requests
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction


class AutonomousBuyerError(RuntimeError):
    def __init__(self, code: str, *, details: Any = None):
        super().__init__(code)
        self.code = code
        self.details = details


class TransactionApproval(Protocol):
    """Explicitly approve or reject one fully described transaction."""

    def approve(self, review: Mapping[str, Any]) -> bool: ...


class BuyerWalletAdapter(Protocol):
    """Wallet-owned signing boundary; implementations must not expose key material."""

    @property
    def wallet_address(self) -> str: ...

    def sign_and_broadcast(
        self,
        transaction_base64: str,
        review: Mapping[str, Any],
    ) -> str: ...


@dataclass(frozen=True)
class BuyerRunnerPolicy:
    allowed_clusters: tuple[str, ...] = ("solana:devnet",)
    timeout_seconds: float = 20.0

    def __post_init__(self):
        if not self.allowed_clusters:
            raise ValueError("at least one cluster must be allowed")
        if not 1 <= self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between 1 and 60")


class AutonomousBuyerRunner:
    """Advance one intent step and stop at every external trust boundary."""

    def __init__(
        self,
        base_url: str,
        *,
        access_token: str,
        wallet: BuyerWalletAdapter,
        approval: TransactionApproval,
        policy: BuyerRunnerPolicy | None = None,
        session: requests.Session | None = None,
    ):
        parsed = urlparse(str(base_url))
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        if parsed.scheme != "https" and not local_http:
            raise ValueError("base_url must use HTTPS outside localhost")
        if not parsed.netloc:
            raise ValueError("base_url must be absolute")
        if len(str(access_token)) < 16:
            raise ValueError("access_token is invalid")
        try:
            Pubkey.from_string(str(wallet.wallet_address))
        except ValueError as exc:
            raise ValueError("wallet_address is invalid") from exc
        self.base_url = str(base_url).rstrip("/")
        self.access_token = str(access_token)
        self.wallet = wallet
        self.approval = approval
        self.policy = policy or BuyerRunnerPolicy()
        self.session = session or requests.Session()

    def step(self, intent_decision_id: str, *, input_asset: str = "USDC") -> dict[str, Any]:
        advanced = self._request(
            "POST",
            "/payments/v1/universal/buyer/intents/advance",
            {"intent_decision_id": intent_decision_id, "input_asset": input_asset},
        )
        if advanced.get("next_action") != "buyer_sign_and_broadcast":
            return advanced
        prepared = advanced.get("result")
        review = self._validate_prepared_transaction(prepared)
        if not self.approval.approve(review):
            return {
                "status": "buyer_signature_not_approved",
                "intent_decision_id": intent_decision_id,
                "next_action": "buyer_sign_and_broadcast",
                "review": review,
            }
        signature = str(
            self.wallet.sign_and_broadcast(str(prepared["transaction_base64"]), review)
        )
        try:
            Signature.from_string(signature)
        except Exception as exc:
            raise AutonomousBuyerError("wallet_returned_invalid_signature") from exc
        return self._request(
            "POST",
            "/payments/v1/universal/buyer/intents/checkout/submit",
            {
                "intent_decision_id": intent_decision_id,
                "quote_id": prepared["quote_id"],
                "tx_signature": signature,
            },
        )

    def _validate_prepared_transaction(self, prepared: Any) -> dict[str, Any]:
        if not isinstance(prepared, dict):
            raise AutonomousBuyerError("prepared_transaction_missing")
        required_flags = {
            "policy_enforced": True,
            "buyer_signature_required": True,
            "transaction_submitted": False,
            "funds_moved": False,
        }
        if any(prepared.get(key) is not expected for key, expected in required_flags.items()):
            raise AutonomousBuyerError("prepared_transaction_safety_flags_invalid")
        if prepared.get("autonomous") is not True:
            raise AutonomousBuyerError("autonomous_policy_not_applied")
        simulation = prepared.get("simulation") or {}
        if simulation.get("status") != "succeeded":
            raise AutonomousBuyerError("transaction_simulation_not_succeeded")
        review = prepared.get("review")
        if not isinstance(review, dict):
            raise AutonomousBuyerError("transaction_review_missing")
        cluster = str(review.get("cluster") or "")
        if cluster not in self.policy.allowed_clusters:
            raise AutonomousBuyerError("transaction_cluster_not_allowed", details=cluster)
        fee_payer = str(review.get("fee_payer") or "")
        if not hmac.compare_digest(fee_payer, str(self.wallet.wallet_address)):
            raise AutonomousBuyerError("transaction_fee_payer_mismatch")
        if not prepared.get("quote_id") or not prepared.get("transaction_base64"):
            raise AutonomousBuyerError("prepared_transaction_incomplete")
        try:
            expires_at = int(prepared["expires_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AutonomousBuyerError("prepared_transaction_expiry_invalid") from exc
        if expires_at <= int(time.time()):
            raise AutonomousBuyerError("prepared_transaction_expired")
        try:
            raw_transaction = base64.b64decode(
                str(prepared["transaction_base64"]), validate=True
            )
            transaction = VersionedTransaction.from_bytes(raw_transaction)
            signer_count = int(transaction.message.header.num_required_signatures)
            required_signers = {
                str(address) for address in transaction.message.account_keys[:signer_count]
            }
            transaction_fee_payer = str(transaction.message.account_keys[0])
        except (ValueError, IndexError) as exc:
            raise AutonomousBuyerError("prepared_transaction_encoding_invalid") from exc
        if not hmac.compare_digest(transaction_fee_payer, fee_payer):
            raise AutonomousBuyerError("transaction_fee_payer_mismatch")
        if str(self.wallet.wallet_address) not in required_signers:
            raise AutonomousBuyerError("buyer_signature_not_required_by_transaction")
        return {
            "cluster": cluster,
            "fee_payer": fee_payer,
            "input": review.get("input"),
            "minimum_iat_output": review.get("minimum_iat_output"),
            "program_id": review.get("program_id"),
            "treasury_vault": review.get("treasury_vault"),
            "iat_destination": review.get("iat_destination"),
            "network_fee": review.get("network_fee"),
            "quote_id": prepared["quote_id"],
            "expires_at": expires_at,
            "simulation": dict(simulation),
        }

    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                self.base_url + path,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Accept": "application/json",
                    "User-Agent": "iat-autonomous-buyer/1.0",
                },
                timeout=self.policy.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AutonomousBuyerError("iat_transport_failed") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise AutonomousBuyerError("iat_response_invalid") from exc
        if not 200 <= int(response.status_code) < 300:
            raise AutonomousBuyerError(
                "iat_request_rejected",
                details={"status_code": response.status_code, "response": body},
            )
        if not isinstance(body, dict):
            raise AutonomousBuyerError("iat_response_invalid")
        return body
