"""Reference local wallet sidecar with a pluggable, non-custodial backend."""

from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
from typing import Any, Mapping, Protocol

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from iat.attested_wallet_signer import build_evidence_message


class WalletSigningBackend(Protocol):
    """External wallet boundary. Implementations retain all key material."""

    @property
    def wallet_address(self) -> str: ...

    def approve_sign_and_broadcast(
        self,
        transaction_base64: str,
        review: Mapping[str, Any],
    ) -> str: ...

    def attest_evidence(
        self,
        *,
        evidence_type: str,
        evidence_id: str,
        evidence_sha256: str,
        observed_at: int,
    ) -> Mapping[str, Any]: ...


class WalletSidecarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = Field(pattern="^sign_and_broadcast_solana_transaction$")
    wallet_address: str = Field(min_length=32, max_length=64)
    transaction_base64: str = Field(min_length=64, max_length=20_000)
    review: dict[str, Any]


class WalletEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = Field(pattern="^attest_iat_evidence$")
    wallet_address: str = Field(min_length=32, max_length=64)
    evidence_type: str = Field(pattern="^buyer_job_journal$")
    evidence_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{3,160}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: int = Field(gt=0)


def create_wallet_sidecar_app(
    backend: WalletSigningBackend,
    *,
    auth_token: str,
    allowed_clusters: tuple[str, ...] = ("solana:devnet",),
    maximum_transaction_ttl_seconds: int = 180,
    maximum_evidence_age_seconds: int = 300,
) -> FastAPI:
    """Create a sidecar app without reading, accepting, or storing private keys."""
    token = str(auth_token)
    if len(token) < 16:
        raise ValueError("auth_token is invalid")
    try:
        wallet = str(Pubkey.from_string(str(backend.wallet_address)))
    except ValueError as exc:
        raise ValueError("backend wallet_address is invalid") from exc
    clusters = frozenset(str(item) for item in allowed_clusters if str(item))
    if not clusters:
        raise ValueError("at least one cluster must be allowed")
    maximum_ttl = max(30, min(int(maximum_transaction_ttl_seconds), 300))
    maximum_evidence_age = max(30, min(int(maximum_evidence_age_seconds), 900))
    replay_lock = threading.RLock()
    completed: dict[str, str] = {}
    evidence_completed: dict[str, dict[str, Any]] = {}
    app = FastAPI(title="IAT Local Wallet Sidecar", docs_url=None, redoc_url=None)

    def authenticate(authorization: str | None) -> None:
        scheme, separator, supplied = str(authorization or "").partition(" ")
        if (
            separator != " "
            or scheme.lower() != "bearer"
            or not hmac.compare_digest(supplied, token)
        ):
            raise HTTPException(status_code=401, detail="invalid_sidecar_token")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ready",
            "wallet_address": wallet,
            "allowed_clusters": sorted(clusters),
            "allowed_evidence_types": ["buyer_job_journal"],
            "key_custody": "external_backend",
        }

    @app.post("/v1/wallet/attest-evidence")
    async def attest_evidence(
        req: WalletEvidenceRequest,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> dict[str, Any]:
        authenticate(authorization)
        if not hmac.compare_digest(req.wallet_address, wallet):
            raise HTTPException(status_code=409, detail="wallet_identity_mismatch")
        now = int(time.time())
        if abs(now - req.observed_at) > maximum_evidence_age:
            raise HTTPException(status_code=422, detail="evidence_observation_out_of_window")
        message = build_evidence_message(
            wallet,
            req.evidence_type,
            req.evidence_id,
            req.evidence_sha256,
            req.observed_at,
        )
        cache_key = hashlib.sha256(message).hexdigest()
        with replay_lock:
            existing = evidence_completed.get(cache_key)
            if existing is not None:
                return {**existing, "idempotent": True}
            try:
                result = dict(
                    backend.attest_evidence(
                        evidence_type=req.evidence_type,
                        evidence_id=req.evidence_id,
                        evidence_sha256=req.evidence_sha256,
                        observed_at=req.observed_at,
                    )
                )
                signature = Signature.from_string(str(result.get("signature") or ""))
            except Exception as exc:
                raise HTTPException(status_code=502, detail="wallet_backend_failed") from exc
            bindings = (
                hmac.compare_digest(str(result.get("wallet_address") or ""), wallet)
                and hmac.compare_digest(
                    str(result.get("evidence_type") or ""), req.evidence_type
                )
                and hmac.compare_digest(
                    str(result.get("evidence_id") or ""), req.evidence_id
                )
                and hmac.compare_digest(
                    str(result.get("evidence_sha256") or ""), req.evidence_sha256
                )
                and str(result.get("observed_at") or "") == str(req.observed_at)
            )
            if not bindings or not signature.verify(Pubkey.from_string(wallet), message):
                raise HTTPException(status_code=502, detail="wallet_evidence_invalid")
            response = {
                "approved": True,
                "wallet_address": wallet,
                "evidence_type": req.evidence_type,
                "evidence_id": req.evidence_id,
                "evidence_sha256": req.evidence_sha256,
                "observed_at": req.observed_at,
                "signature": str(signature),
            }
            evidence_completed[cache_key] = response
        return {**response, "idempotent": False}

    @app.post("/v1/wallet/sign-and-broadcast")
    async def sign_and_broadcast(
        req: WalletSidecarRequest,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> dict[str, Any]:
        authenticate(authorization)
        if not hmac.compare_digest(req.wallet_address, wallet):
            raise HTTPException(status_code=409, detail="wallet_identity_mismatch")
        review = dict(req.review)
        if not hmac.compare_digest(str(review.get("fee_payer") or ""), wallet):
            raise HTTPException(status_code=409, detail="review_fee_payer_mismatch")
        if str(review.get("cluster") or "") not in clusters:
            raise HTTPException(status_code=403, detail="cluster_not_allowed")
        simulation = review.get("simulation")
        if not isinstance(simulation, dict) or simulation.get("status") != "succeeded":
            raise HTTPException(status_code=409, detail="simulation_not_succeeded")
        try:
            expires_at = int(review["expires_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="transaction_expiry_invalid") from exc
        now = int(time.time())
        if expires_at <= now:
            raise HTTPException(status_code=410, detail="transaction_expired")
        if expires_at > now + maximum_ttl:
            raise HTTPException(status_code=422, detail="transaction_expiry_too_distant")
        try:
            raw = base64.b64decode(req.transaction_base64, validate=True)
            transaction = VersionedTransaction.from_bytes(raw)
            signer_count = int(transaction.message.header.num_required_signatures)
            required_signers = {
                str(address) for address in transaction.message.account_keys[:signer_count]
            }
            fee_payer = str(transaction.message.account_keys[0])
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=422, detail="transaction_encoding_invalid") from exc
        if not hmac.compare_digest(fee_payer, wallet) or wallet not in required_signers:
            raise HTTPException(status_code=409, detail="transaction_signer_mismatch")

        digest = hashlib.sha256(raw).hexdigest()
        with replay_lock:
            existing = completed.get(digest)
            if existing:
                return {
                    "approved": True,
                    "wallet_address": wallet,
                    "tx_signature": existing,
                    "idempotent": True,
                }
            try:
                signature = str(
                    backend.approve_sign_and_broadcast(req.transaction_base64, review)
                )
                Signature.from_string(signature)
            except Exception as exc:
                raise HTTPException(status_code=502, detail="wallet_backend_failed") from exc
            completed[digest] = signature
        return {
            "approved": True,
            "wallet_address": wallet,
            "tx_signature": signature,
            "idempotent": False,
        }

    return app
