"""Public, signature-authorized registry for bounded protocol evidence."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from solders.pubkey import Pubkey
from solders.signature import Signature

from iat.api import db
from iat.attested_wallet_signer import build_evidence_message


router = APIRouter(prefix="/protocol/v1/evidence", tags=["protocol-evidence"])
MAX_EVIDENCE_AGE_SECONDS = 86_400
MAX_FUTURE_SKEW_SECONDS = 60


def _now() -> int:
    return int(time.time())


class ProtocolEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: str = Field(pattern="^buyer_job_journal$")
    evidence_id: str = Field(min_length=1, max_length=128)
    evidence_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    observed_at: int = Field(gt=0)
    wallet_address: str = Field(min_length=32, max_length=64)
    signature: str = Field(min_length=64, max_length=128)


def init_protocol_evidence_db() -> None:
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_execution_evidence (
                receipt_id TEXT PRIMARY KEY,
                evidence_type TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                evidence_sha256 TEXT NOT NULL,
                observed_at BIGINT NOT NULL,
                wallet_address TEXT NOT NULL,
                signature TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                received_at BIGINT NOT NULL,
                UNIQUE(wallet_address, evidence_type, evidence_id)
            )
            """
        )
        cursor.execute(
            """CREATE INDEX IF NOT EXISTS idx_protocol_evidence_lookup
               ON protocol_execution_evidence(evidence_id, wallet_address)"""
        )
        connection.commit()
    finally:
        db.release_conn(connection)


def _canonical_receipt(payload: dict[str, Any], received_at: int) -> bytes:
    return json.dumps(
        {
            "evidence_id": payload["evidence_id"],
            "evidence_sha256": payload["evidence_sha256"],
            "evidence_type": payload["evidence_type"],
            "observed_at": payload["observed_at"],
            "received_at": received_at,
            "signature": payload["signature"],
            "wallet_address": payload["wallet_address"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _public_record(row: Any) -> dict[str, Any]:
    record = dict(row)
    return {
        "status": "protocol_evidence_registered",
        "receipt_id": record["receipt_id"],
        "evidence_type": record["evidence_type"],
        "evidence_id": record["evidence_id"],
        "evidence_sha256": record["evidence_sha256"],
        "observed_at": int(record["observed_at"]),
        "wallet_address": record["wallet_address"],
        "signature": record["signature"],
        "receipt_sha256": record["receipt_sha256"],
        "received_at": int(record["received_at"]),
        "effect": "evidence_only",
    }


def _find(cursor: Any, evidence_id: str, wallet_address: str) -> Any:
    placeholder = db.qmark()
    cursor.execute(
        f"""SELECT * FROM protocol_execution_evidence
            WHERE evidence_id = {placeholder} AND wallet_address = {placeholder}""",
        (evidence_id, wallet_address),
    )
    return cursor.fetchone()


@router.post("")
def publish_protocol_evidence(request: ProtocolEvidenceRequest) -> dict[str, Any]:
    payload = request.model_dump()
    now = _now()
    if request.observed_at < now - MAX_EVIDENCE_AGE_SECONDS:
        raise HTTPException(status_code=422, detail="protocol_evidence_expired")
    if request.observed_at > now + MAX_FUTURE_SKEW_SECONDS:
        raise HTTPException(status_code=422, detail="protocol_evidence_from_future")
    try:
        public_key = Pubkey.from_string(request.wallet_address)
        signature = Signature.from_string(request.signature)
        message = build_evidence_message(
            request.wallet_address,
            request.evidence_type,
            request.evidence_id,
            request.evidence_sha256,
            request.observed_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="protocol_evidence_invalid") from exc
    if not signature.verify(public_key, message):
        raise HTTPException(status_code=403, detail="protocol_evidence_signature_invalid")

    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        existing = _find(cursor, request.evidence_id, request.wallet_address)
        if existing is not None:
            record = dict(existing)
            if (
                record["evidence_type"] != request.evidence_type
                or record["evidence_sha256"] != request.evidence_sha256
                or int(record["observed_at"]) != request.observed_at
                or record["signature"] != request.signature
            ):
                raise HTTPException(status_code=409, detail="protocol_evidence_conflict")
            return _public_record(existing)
        received_at = now
        receipt_sha256 = hashlib.sha256(
            _canonical_receipt(payload, received_at)
        ).hexdigest()
        receipt_id = "per_" + receipt_sha256[:24]
        placeholder = db.qmark()
        cursor.execute(
            f"""INSERT INTO protocol_execution_evidence (
                    receipt_id, evidence_type, evidence_id, evidence_sha256,
                    observed_at, wallet_address, signature, receipt_sha256,
                    received_at
                ) VALUES ({', '.join([placeholder] * 9)})""",
            (
                receipt_id,
                request.evidence_type,
                request.evidence_id,
                request.evidence_sha256,
                request.observed_at,
                request.wallet_address,
                request.signature,
                receipt_sha256,
                received_at,
            ),
        )
        connection.commit()
        return _public_record(_find(cursor, request.evidence_id, request.wallet_address))
    finally:
        db.release_conn(connection)


@router.get("/{evidence_id}")
def get_protocol_evidence(
    evidence_id: str,
    wallet_address: str = Query(min_length=32, max_length=64),
) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        record = _find(connection.cursor(), evidence_id, wallet_address)
        if record is None:
            raise HTTPException(status_code=404, detail="protocol_evidence_not_found")
        return _public_record(record)
    finally:
        db.release_conn(connection)
