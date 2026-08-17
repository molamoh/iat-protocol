"""Attested HTTPS transaction signer for agent wallets and HSM gateways."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
import time
from typing import Any, Mapping
from urllib.parse import urlparse

import requests
from solders.pubkey import Pubkey
from solders.signature import Signature


ATTESTATION_DOMAIN = b"IAT_AGENT_WALLET_ATTESTATION_V1"
EVIDENCE_DOMAIN = b"IAT_AGENT_EVIDENCE_ATTESTATION_V1"
EVIDENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{3,160}$")


class AttestedWalletSignerError(RuntimeError):
    def __init__(self, code: str, *, details: Any = None):
        super().__init__(code)
        self.code = code
        self.details = details


class AttestedHTTPSDetachedSigner:
    """Authenticate a remote signer by wallet proof before requesting signatures."""

    def __init__(
        self,
        endpoint: str,
        *,
        wallet_address: str,
        auth_token: str,
        timeout_seconds: float = 15.0,
        attestation_ttl_seconds: int = 300,
        allow_remote_https: bool = True,
        session: requests.Session | None = None,
    ):
        parsed = urlparse(str(endpoint))
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("signer endpoint must not contain credentials, query or fragment")
        if not parsed.hostname or not parsed.netloc:
            raise ValueError("signer endpoint must be absolute")
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = False
        if loopback:
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("loopback signer endpoint must use HTTP(S)")
        elif not allow_remote_https or parsed.scheme != "https":
            raise ValueError("remote signer endpoint requires HTTPS")
        try:
            self._wallet_pubkey = Pubkey.from_string(str(wallet_address))
        except ValueError as exc:
            raise ValueError("wallet_address is invalid") from exc
        if len(str(auth_token)) < 16:
            raise ValueError("signer auth_token is invalid")
        if not 1 <= float(timeout_seconds) <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.endpoint = str(endpoint).rstrip("/")
        self._auth_token = str(auth_token)
        self.timeout_seconds = float(timeout_seconds)
        self.attestation_ttl_seconds = max(30, min(int(attestation_ttl_seconds), 900))
        self.session = session or requests.Session()
        self._attested_until = 0
        self._attestation_lock = threading.RLock()

    @property
    def wallet_address(self) -> str:
        return str(self._wallet_pubkey)

    def verify_identity(self, *, force: bool = False) -> dict[str, Any]:
        now = int(time.time())
        with self._attestation_lock:
            if not force and now < self._attested_until:
                return {
                    "status": "wallet_identity_attested",
                    "wallet_address": self.wallet_address,
                    "cached": True,
                    "attested_until": self._attested_until,
                }
            nonce = secrets.token_urlsafe(32)
            message = b"\n".join(
                [ATTESTATION_DOMAIN, self.wallet_address.encode("ascii"), nonce.encode("ascii")]
            )
            body = self._post(
                "/v1/identity/attest",
                {
                    "operation": "attest_solana_wallet_control",
                    "wallet_address": self.wallet_address,
                    "nonce": nonce,
                    "message_base64": base64.b64encode(message).decode(),
                },
            )
            if not hmac.compare_digest(
                str(body.get("wallet_address") or ""), self.wallet_address
            ) or not hmac.compare_digest(str(body.get("nonce") or ""), nonce):
                raise AttestedWalletSignerError("wallet_attestation_binding_mismatch")
            try:
                signature = Signature.from_string(str(body.get("signature") or ""))
            except Exception as exc:
                raise AttestedWalletSignerError("wallet_attestation_signature_invalid") from exc
            if not signature.verify(self._wallet_pubkey, message):
                raise AttestedWalletSignerError("wallet_attestation_signature_invalid")
            self._attested_until = now + self.attestation_ttl_seconds
            return {
                "status": "wallet_identity_attested",
                "wallet_address": self.wallet_address,
                "cached": False,
                "attested_until": self._attested_until,
            }

    def sign_transaction(
        self,
        transaction_base64: str,
        review: Mapping[str, Any],
    ) -> str:
        self.verify_identity()
        transaction = str(transaction_base64)
        try:
            raw = base64.b64decode(transaction, validate=True)
        except ValueError as exc:
            raise AttestedWalletSignerError("transaction_encoding_invalid") from exc
        transaction_digest = hashlib.sha256(raw).hexdigest()
        request_id = "wsg_" + secrets.token_urlsafe(24)
        body = self._post(
            "/v1/transactions/sign",
            {
                "operation": "sign_solana_transaction",
                "request_id": request_id,
                "wallet_address": self.wallet_address,
                "transaction_sha256": transaction_digest,
                "transaction_base64": transaction,
                "review": dict(review),
            },
        )
        bindings = (
            hmac.compare_digest(str(body.get("request_id") or ""), request_id)
            and hmac.compare_digest(
                str(body.get("wallet_address") or ""), self.wallet_address
            )
            and hmac.compare_digest(
                str(body.get("transaction_sha256") or ""), transaction_digest
            )
        )
        if not bindings:
            raise AttestedWalletSignerError("signed_transaction_binding_mismatch")
        signed = str(body.get("signed_transaction_base64") or "")
        try:
            base64.b64decode(signed, validate=True)
        except ValueError as exc:
            raise AttestedWalletSignerError("signed_transaction_encoding_invalid") from exc
        return signed

    def sign_evidence(
        self,
        *,
        evidence_type: str,
        evidence_id: str,
        evidence_sha256: str,
        observed_at: int,
    ) -> dict[str, Any]:
        """Sign one domain-separated evidence digest; never signs a transaction."""
        self.verify_identity()
        kind = str(evidence_type)
        identifier = str(evidence_id)
        digest = str(evidence_sha256).lower()
        if kind != "buyer_job_journal":
            raise ValueError("evidence_type_not_allowed")
        if not EVIDENCE_ID_PATTERN.fullmatch(identifier):
            raise ValueError("evidence_id_invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("evidence_sha256_invalid")
        try:
            timestamp = int(observed_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("evidence_observed_at_invalid") from exc
        if timestamp < 1:
            raise ValueError("evidence_observed_at_invalid")
        message = b"\n".join(
            [
                EVIDENCE_DOMAIN,
                self.wallet_address.encode("ascii"),
                kind.encode("ascii"),
                identifier.encode("ascii"),
                digest.encode("ascii"),
                str(timestamp).encode("ascii"),
            ]
        )
        body = self._post(
            "/v1/evidence/sign",
            {
                "operation": "sign_iat_evidence",
                "wallet_address": self.wallet_address,
                "evidence_type": kind,
                "evidence_id": identifier,
                "evidence_sha256": digest,
                "observed_at": timestamp,
                "message_base64": base64.b64encode(message).decode(),
            },
        )
        bindings = (
            hmac.compare_digest(str(body.get("wallet_address") or ""), self.wallet_address)
            and hmac.compare_digest(str(body.get("evidence_type") or ""), kind)
            and hmac.compare_digest(str(body.get("evidence_id") or ""), identifier)
            and hmac.compare_digest(str(body.get("evidence_sha256") or ""), digest)
            and str(body.get("observed_at") or "") == str(timestamp)
        )
        if not bindings:
            raise AttestedWalletSignerError("evidence_signature_binding_mismatch")
        try:
            signature = Signature.from_string(str(body.get("signature") or ""))
        except Exception as exc:
            raise AttestedWalletSignerError("evidence_signature_invalid") from exc
        if not signature.verify(self._wallet_pubkey, message):
            raise AttestedWalletSignerError("evidence_signature_invalid")
        return {
            "status": "evidence_signed",
            "wallet_address": self.wallet_address,
            "evidence_type": kind,
            "evidence_id": identifier,
            "evidence_sha256": digest,
            "observed_at": timestamp,
            "message_base64": base64.b64encode(message).decode(),
            "signature": str(signature),
        }

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(
                self.endpoint + path,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._auth_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "iat-attested-wallet-signer/1.0",
                },
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise AttestedWalletSignerError("wallet_signer_unavailable") from exc
        if 300 <= int(response.status_code) < 400:
            raise AttestedWalletSignerError("wallet_signer_redirect_rejected")
        try:
            body = response.json()
        except ValueError as exc:
            raise AttestedWalletSignerError("wallet_signer_response_invalid") from exc
        if not 200 <= int(response.status_code) < 300:
            raise AttestedWalletSignerError(
                "wallet_signer_rejected",
                details={"status_code": response.status_code, "response": body},
            )
        if not isinstance(body, dict):
            raise AttestedWalletSignerError("wallet_signer_response_invalid")
        return body
