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


class WalletSigningBackend(Protocol):
    """External wallet boundary. Implementations retain all key material."""

    @property
    def wallet_address(self) -> str: ...

    def approve_sign_and_broadcast(
        self,
        transaction_base64: str,
        review: Mapping[str, Any],
    ) -> str: ...


class WalletSidecarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = Field(pattern="^sign_and_broadcast_solana_transaction$")
    wallet_address: str = Field(min_length=32, max_length=64)
    transaction_base64: str = Field(min_length=64, max_length=20_000)
    review: dict[str, Any]


def create_wallet_sidecar_app(
    backend: WalletSigningBackend,
    *,
    auth_token: str,
    allowed_clusters: tuple[str, ...] = ("solana:devnet",),
    maximum_transaction_ttl_seconds: int = 180,
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
    replay_lock = threading.RLock()
    completed: dict[str, str] = {}
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
            "key_custody": "external_backend",
        }

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
