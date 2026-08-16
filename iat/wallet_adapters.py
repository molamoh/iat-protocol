"""Non-custodial wallet adapters for autonomous buyer agents."""

from __future__ import annotations

import hmac
import ipaddress
from typing import Any, Mapping
from urllib.parse import urlparse

import requests
from solders.pubkey import Pubkey
from solders.signature import Signature


class WalletAdapterError(RuntimeError):
    def __init__(self, code: str, *, details: Any = None):
        super().__init__(code)
        self.code = code
        self.details = details


class LocalWalletRPCAdapter:
    """Delegate signing to a separately secured loopback wallet sidecar."""

    def __init__(
        self,
        endpoint: str,
        *,
        wallet_address: str,
        auth_token: str,
        timeout_seconds: float = 15.0,
        allow_remote_https: bool = False,
        session: requests.Session | None = None,
    ):
        parsed = urlparse(str(endpoint))
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("wallet endpoint must not contain credentials, query or fragment")
        if not parsed.hostname or not parsed.netloc:
            raise ValueError("wallet endpoint must be absolute")
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = False
        if loopback:
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("loopback wallet endpoint must use HTTP(S)")
        elif not allow_remote_https or parsed.scheme != "https":
            raise ValueError("remote wallet endpoint requires explicit HTTPS opt-in")
        try:
            Pubkey.from_string(str(wallet_address))
        except ValueError as exc:
            raise ValueError("wallet_address is invalid") from exc
        if len(str(auth_token)) < 16:
            raise ValueError("wallet auth_token is invalid")
        if not 1 <= float(timeout_seconds) <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.endpoint = str(endpoint).rstrip("/")
        self._wallet_address = str(wallet_address)
        self._auth_token = str(auth_token)
        self.timeout_seconds = float(timeout_seconds)
        self.session = session or requests.Session()

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    def sign_and_broadcast(
        self,
        transaction_base64: str,
        review: Mapping[str, Any],
    ) -> str:
        safe_review = dict(review)
        if not hmac.compare_digest(
            str(safe_review.get("fee_payer") or ""), self._wallet_address
        ):
            raise WalletAdapterError("wallet_review_fee_payer_mismatch")
        try:
            response = self.session.post(
                self.endpoint + "/v1/wallet/sign-and-broadcast",
                json={
                    "operation": "sign_and_broadcast_solana_transaction",
                    "wallet_address": self._wallet_address,
                    "transaction_base64": str(transaction_base64),
                    "review": safe_review,
                },
                headers={
                    "Authorization": f"Bearer {self._auth_token}",
                    "Accept": "application/json",
                    "User-Agent": "iat-wallet-adapter/1.0",
                },
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise WalletAdapterError("wallet_sidecar_unavailable") from exc
        if 300 <= int(response.status_code) < 400:
            raise WalletAdapterError("wallet_sidecar_redirect_rejected")
        try:
            body = response.json()
        except ValueError as exc:
            raise WalletAdapterError("wallet_sidecar_response_invalid") from exc
        if not 200 <= int(response.status_code) < 300:
            raise WalletAdapterError(
                "wallet_sidecar_rejected",
                details={"status_code": response.status_code, "response": body},
            )
        if not isinstance(body, dict) or body.get("approved") is not True:
            raise WalletAdapterError("wallet_sidecar_did_not_approve")
        if not hmac.compare_digest(
            str(body.get("wallet_address") or ""), self._wallet_address
        ):
            raise WalletAdapterError("wallet_sidecar_identity_mismatch")
        signature = str(body.get("tx_signature") or "")
        try:
            Signature.from_string(signature)
        except Exception as exc:
            raise WalletAdapterError("wallet_sidecar_signature_invalid") from exc
        return signature
