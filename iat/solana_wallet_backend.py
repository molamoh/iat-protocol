"""Concrete non-custodial Solana RPC backend for the local wallet sidecar."""

from __future__ import annotations

import base64
import hmac
import ipaddress
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import requests
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction


class SolanaWalletBackendError(RuntimeError):
    def __init__(self, code: str, *, details: Any = None):
        super().__init__(code)
        self.code = code
        self.details = details


class DetachedTransactionSigner(Protocol):
    """HSM, agent wallet, or Wallet Standard bridge retaining its own keys."""

    @property
    def wallet_address(self) -> str: ...

    def sign_transaction(
        self,
        transaction_base64: str,
        review: Mapping[str, Any],
    ) -> str: ...

    def sign_evidence(
        self,
        *,
        evidence_type: str,
        evidence_id: str,
        evidence_sha256: str,
        observed_at: int,
    ) -> Mapping[str, Any]: ...


class TransactionReviewApproval(Protocol):
    def approve(self, review: Mapping[str, Any]) -> bool: ...


class SolanaRPCWalletBackend:
    """Approve, externally sign, verify, and broadcast one unchanged transaction."""

    def __init__(
        self,
        *,
        signer: DetachedTransactionSigner,
        approval: TransactionReviewApproval,
        rpc_url: str = "https://api.devnet.solana.com",
        cluster: str = "solana:devnet",
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ):
        try:
            self._wallet_pubkey = Pubkey.from_string(str(signer.wallet_address))
        except ValueError as exc:
            raise ValueError("signer wallet_address is invalid") from exc
        parsed = urlparse(str(rpc_url))
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("rpc_url must not contain credentials, query or fragment")
        try:
            loopback = bool(parsed.hostname) and ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = False
        if parsed.scheme != "https" and not (loopback and parsed.scheme == "http"):
            raise ValueError("rpc_url must use HTTPS outside loopback")
        if cluster != "solana:devnet":
            raise ValueError("this backend release permits solana:devnet only")
        if not 1 <= float(timeout_seconds) <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.signer = signer
        self.approval = approval
        self.rpc_url = str(rpc_url)
        self.cluster = cluster
        self.timeout_seconds = float(timeout_seconds)
        self.session = session or requests.Session()

    @property
    def wallet_address(self) -> str:
        return str(self._wallet_pubkey)

    def approve_sign_and_broadcast(
        self,
        transaction_base64: str,
        review: Mapping[str, Any],
    ) -> str:
        safe_review = dict(review)
        if safe_review.get("cluster") != self.cluster:
            raise SolanaWalletBackendError("backend_cluster_mismatch")
        if not hmac.compare_digest(
            str(safe_review.get("fee_payer") or ""), self.wallet_address
        ):
            raise SolanaWalletBackendError("backend_fee_payer_mismatch")
        if not self.approval.approve(safe_review):
            raise SolanaWalletBackendError("transaction_not_approved")
        prepared = self._decode_transaction(transaction_base64, "prepared_transaction_invalid")
        signer_count = int(prepared.message.header.num_required_signatures)
        required_signers = list(prepared.message.account_keys[:signer_count])
        if not required_signers or required_signers[0] != self._wallet_pubkey:
            raise SolanaWalletBackendError("buyer_not_transaction_fee_payer")
        wallet_index = required_signers.index(self._wallet_pubkey)
        if prepared.signatures[wallet_index] != Signature.default():
            raise SolanaWalletBackendError("buyer_signature_slot_not_empty")

        signed_base64 = str(
            self.signer.sign_transaction(str(transaction_base64), safe_review)
        )
        signed = self._decode_transaction(signed_base64, "signed_transaction_invalid")
        if bytes(signed.message) != bytes(prepared.message):
            raise SolanaWalletBackendError("signer_changed_transaction_message")
        if len(signed.signatures) != len(prepared.signatures):
            raise SolanaWalletBackendError("signer_changed_signature_layout")
        for index, previous in enumerate(prepared.signatures):
            if index != wallet_index and signed.signatures[index] != previous:
                raise SolanaWalletBackendError("signer_changed_existing_signature")
        buyer_signature = signed.signatures[wallet_index]
        if buyer_signature == Signature.default() or not buyer_signature.verify(
            self._wallet_pubkey, bytes(signed.message)
        ):
            raise SolanaWalletBackendError("buyer_signature_invalid")

        try:
            response = self.session.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        signed_base64,
                        {
                            "encoding": "base64",
                            "skipPreflight": False,
                            "preflightCommitment": "confirmed",
                            "maxRetries": 3,
                        },
                    ],
                },
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SolanaWalletBackendError("solana_rpc_unavailable") from exc
        if not isinstance(payload, dict) or payload.get("error") or not payload.get("result"):
            raise SolanaWalletBackendError("solana_rpc_rejected", details=payload)
        rpc_signature = str(payload["result"])
        if not hmac.compare_digest(rpc_signature, str(signed.signatures[0])):
            raise SolanaWalletBackendError("solana_rpc_signature_mismatch")
        return rpc_signature

    def attest_evidence(
        self,
        *,
        evidence_type: str,
        evidence_id: str,
        evidence_sha256: str,
        observed_at: int,
    ) -> Mapping[str, Any]:
        """Delegate bounded evidence signing without RPC or transaction handling."""
        return self.signer.sign_evidence(
            evidence_type=evidence_type,
            evidence_id=evidence_id,
            evidence_sha256=evidence_sha256,
            observed_at=observed_at,
        )

    @staticmethod
    def _decode_transaction(value: str, code: str) -> VersionedTransaction:
        try:
            return VersionedTransaction.from_bytes(
                base64.b64decode(str(value), validate=True)
            )
        except ValueError as exc:
            raise SolanaWalletBackendError(code) from exc
