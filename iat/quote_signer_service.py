"""Private FastAPI surface for the isolated IAT devnet quote signer."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from iat.quote_signer import LocalDevnetQuoteSigner, QuoteSigningRejected


logger = logging.getLogger("iat.quote_signer")


class SignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,96}$")
    quote_id: str = Field(pattern=r"^uq_[a-f0-9]{32}$")
    expires_at: int
    transaction_base64: str = Field(min_length=64, max_length=20_000)
    instruction_plan: dict


app = FastAPI(
    title="IAT Quote Signer",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
_lock = threading.Lock()
_signed_requests: dict[str, tuple[str, dict]] = {}


def _now() -> int:
    return int(time.time())


def _shared_secret() -> bytes:
    value = os.getenv("IAT_QUOTE_SIGNER_SHARED_SECRET", "").encode()
    if len(value) < 32:
        raise QuoteSigningRejected("shared_secret_unavailable")
    return value


def _authenticate(raw: bytes, timestamp: str, signature: str) -> None:
    try:
        observed_at = int(timestamp)
    except ValueError as exc:
        raise QuoteSigningRejected("invalid_auth_timestamp") from exc
    now = _now()
    if abs(now - observed_at) > 30:
        raise QuoteSigningRejected("auth_timestamp_outside_window")
    expected = hmac.new(
        _shared_secret(),
        timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise QuoteSigningRejected("invalid_auth_signature")


def _signer() -> LocalDevnetQuoteSigner:
    if os.getenv("IAT_QUOTE_SIGNER_ENABLED", "false").lower() != "true":
        raise QuoteSigningRejected("quote_signer_disabled")
    if os.getenv("IAT_QUOTE_SIGNER_ALLOW_LOCAL_KEYPAIR", "false").lower() != "true":
        raise QuoteSigningRejected("local_keypair_backend_disabled")
    return LocalDevnetQuoteSigner.from_file(
        os.getenv("IAT_QUOTE_SIGNER_KEYPAIR_PATH", ""),
        cluster=os.getenv("IAT_QUOTE_SIGNER_CLUSTER", "devnet"),
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "enabled": os.getenv("IAT_QUOTE_SIGNER_ENABLED", "false").lower() == "true",
        "cluster": os.getenv("IAT_QUOTE_SIGNER_CLUSTER", "devnet"),
        "backend": "local_devnet_keypair",
        "private_api": True,
    }


@app.post("/v1/sign")
async def sign_quote(
    request: Request,
    x_iat_signer_timestamp: str = Header(alias="X-IAT-Signer-Timestamp"),
    x_iat_signer_signature: str = Header(alias="X-IAT-Signer-Signature"),
):
    raw = await request.body()
    try:
        _authenticate(raw, x_iat_signer_timestamp, x_iat_signer_signature)
        payload = SignRequest.model_validate_json(raw)
        request_hash = hashlib.sha256(raw).hexdigest()
        with _lock:
            existing = _signed_requests.get(payload.request_id)
            if existing:
                if existing[0] != request_hash:
                    raise QuoteSigningRejected("request_id_reused")
                return {**existing[1], "idempotent": True}
        result = _signer().sign(
            transaction_base64=payload.transaction_base64,
            instruction_plan=payload.instruction_plan,
            expires_at=payload.expires_at,
            now=_now(),
        )
        response = {
            "status": "signed",
            "request_id": payload.request_id,
            "quote_id": payload.quote_id,
            "transaction_base64": result.transaction_base64,
            "message_hash": result.message_hash,
            "quote_authority": result.quote_authority,
            "expires_at": result.expires_at,
            "idempotent": False,
        }
        with _lock:
            _signed_requests[payload.request_id] = (request_hash, response)
        return response
    except QuoteSigningRejected as exc:
        logger.warning("quote_signer_rejected reason=%s", str(exc))
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("quote_signer_rejected reason=invalid_signing_request")
        raise HTTPException(status_code=422, detail="invalid_signing_request") from exc
