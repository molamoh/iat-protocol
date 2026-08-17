"""Public, signature-authorized registry for bounded protocol evidence."""

from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from solders.pubkey import Pubkey
from solders.signature import Signature

from iat.api import db
from iat.attested_wallet_signer import build_evidence_message
from iat.acceptance import AcceptanceCriteria, evaluate_acceptance
from iat.checkout_delivery import get_delivery
from iat.checkout_receipt import get_delivery_receipt, settlement_release_receipt_gate


router = APIRouter(prefix="/protocol/v1/evidence", tags=["protocol-evidence"])
validation_router = APIRouter(
    prefix="/protocol/v1/delivery-validations",
    tags=["protocol-evidence"],
)
quality_router = APIRouter(
    prefix="/protocol/v1/quality-validations",
    tags=["protocol-evidence"],
)
settlement_eligibility_router = APIRouter(
    prefix="/protocol/v1/settlement-eligibility",
    tags=["protocol-evidence"],
)
settlement_execution_plan_router = APIRouter(
    prefix="/protocol/v1/settlement-execution-plans",
    tags=["protocol-evidence"],
)
settlement_authorization_router = APIRouter(
    prefix="/protocol/v1/settlement-authorizations",
    tags=["protocol-evidence"],
)
settlement_simulation_router = APIRouter(
    prefix="/protocol/v1/settlement-simulations",
    tags=["protocol-evidence"],
)
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
            """
            CREATE TABLE IF NOT EXISTS protocol_settlement_eligibility (
                eligibility_id TEXT PRIMARY KEY,
                quality_validation_id TEXT NOT NULL UNIQUE,
                delivery_validation_id TEXT NOT NULL,
                evidence_receipt_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                quote_id TEXT NOT NULL,
                settlement_id TEXT,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                eligibility_sha256 TEXT NOT NULL,
                evaluated_at BIGINT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_settlement_execution_plans (
                plan_id TEXT PRIMARY KEY,
                eligibility_id TEXT NOT NULL UNIQUE,
                quality_validation_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                winner_wallet TEXT,
                treasury_wallet TEXT,
                gross_amount_minor BIGINT,
                protocol_commission_amount_minor BIGINT,
                seller_payout_amount_minor BIGINT,
                decision TEXT NOT NULL,
                blockers_json TEXT NOT NULL,
                receipt_gate_json TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                plan_sha256 TEXT NOT NULL,
                evaluated_at BIGINT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_settlement_authorizations (
                authorization_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL UNIQUE,
                eligibility_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                authorized_by TEXT NOT NULL,
                authorization_mode TEXT NOT NULL,
                authorization_reason TEXT NOT NULL,
                financial_release_confidence REAL,
                financial_risk_score REAL,
                receipt_gate_json TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                authorization_sha256 TEXT NOT NULL,
                authorized_at BIGINT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_settlement_simulations (
                simulation_id TEXT PRIMARY KEY,
                authorization_id TEXT NOT NULL UNIQUE,
                plan_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                cluster TEXT NOT NULL,
                genesis_hash TEXT NOT NULL,
                commitment TEXT NOT NULL,
                token_program TEXT NOT NULL,
                mint TEXT NOT NULL,
                mint_decimals INTEGER NOT NULL,
                fee_payer TEXT NOT NULL,
                escrow_authority TEXT NOT NULL,
                source_token_account TEXT NOT NULL,
                treasury_token_account TEXT NOT NULL,
                winner_token_account TEXT NOT NULL,
                gross_amount_minor BIGINT NOT NULL,
                protocol_commission_amount_minor BIGINT NOT NULL,
                seller_payout_amount_minor BIGINT NOT NULL,
                instruction_count INTEGER NOT NULL,
                required_signature_count INTEGER NOT NULL,
                unsigned_transaction_sha256 TEXT NOT NULL,
                simulation_logs_sha256 TEXT NOT NULL,
                units_consumed BIGINT,
                context_slot BIGINT,
                policy_version TEXT NOT NULL,
                simulation_sha256 TEXT NOT NULL,
                simulated_at BIGINT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_quality_validations (
                quality_validation_id TEXT PRIMARY KEY,
                delivery_validation_id TEXT NOT NULL UNIQUE,
                evidence_receipt_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                criteria_sha256 TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                checks_json TEXT NOT NULL,
                passed_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                quality_validation_sha256 TEXT NOT NULL,
                evaluated_at BIGINT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_delivery_validations (
                validation_id TEXT PRIMARY KEY,
                evidence_receipt_id TEXT NOT NULL UNIQUE,
                evidence_id TEXT NOT NULL,
                wallet_address TEXT NOT NULL,
                order_id TEXT NOT NULL,
                quote_id TEXT NOT NULL,
                tx_signature TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                inbox_signature_status TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                validation_sha256 TEXT NOT NULL,
                evaluated_at BIGINT NOT NULL
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


def _find_receipt(cursor: Any, receipt_id: str) -> Any:
    placeholder = db.qmark()
    cursor.execute(
        f"SELECT * FROM protocol_execution_evidence WHERE receipt_id = {placeholder}",
        (receipt_id,),
    )
    return cursor.fetchone()


def _find_validation(cursor: Any, receipt_id: str) -> Any:
    placeholder = db.qmark()
    cursor.execute(
        f"""SELECT * FROM protocol_delivery_validations
            WHERE evidence_receipt_id = {placeholder}""",
        (receipt_id,),
    )
    return cursor.fetchone()


def _public_validation(row: Any) -> dict[str, Any]:
    record = dict(row)
    return {
        "status": "protocol_delivery_validation_recorded",
        **record,
        "effect": "evidence_only",
        "quality_verified": False,
    }


def _find_quality_validation(cursor: Any, delivery_validation_id: str) -> Any:
    placeholder = db.qmark()
    cursor.execute(
        f"""SELECT * FROM protocol_quality_validations
            WHERE delivery_validation_id = {placeholder}""",
        (delivery_validation_id,),
    )
    return cursor.fetchone()


def _public_quality_validation(row: Any) -> dict[str, Any]:
    record = dict(row)
    try:
        checks = json.loads(record.pop("checks_json"))
    except (TypeError, json.JSONDecodeError):
        checks = []
    return {
        "status": "protocol_quality_validation_recorded",
        **record,
        "checks": checks,
        "effect": "evidence_only",
        "content_disclosed": False,
    }


def _find_settlement_eligibility(cursor: Any, quality_validation_id: str) -> Any:
    placeholder = db.qmark()
    cursor.execute(
        f"""SELECT * FROM protocol_settlement_eligibility
            WHERE quality_validation_id = {placeholder}""",
        (quality_validation_id,),
    )
    return cursor.fetchone()


def _public_settlement_eligibility(row: Any) -> dict[str, Any]:
    return {
        "status": "protocol_settlement_eligibility_recorded",
        **dict(row),
        "effect": "eligibility_only",
        "funds_moved": False,
        "transaction_signed": False,
        "transaction_broadcast": False,
    }


def _find_settlement_execution_plan(cursor: Any, eligibility_id: str) -> Any:
    placeholder = db.qmark()
    cursor.execute(
        f"""SELECT * FROM protocol_settlement_execution_plans
            WHERE eligibility_id = {placeholder}""",
        (eligibility_id,),
    )
    return cursor.fetchone()


def _public_settlement_execution_plan(row: Any) -> dict[str, Any]:
    record = dict(row)
    for field in ("blockers_json", "receipt_gate_json"):
        try:
            record[field.removesuffix("_json")] = json.loads(record.pop(field))
        except (TypeError, json.JSONDecodeError):
            record[field.removesuffix("_json")] = [] if field == "blockers_json" else {}
    return {
        "status": "protocol_settlement_execution_plan_recorded",
        **record,
        "effect": "planning_only",
        "execution_enabled": False,
        "transaction_built": False,
        "simulation_performed": False,
        "transaction_signed": False,
        "transaction_broadcast": False,
        "funds_moved": False,
    }


def _valid_wallet(value: Any) -> bool:
    try:
        Pubkey.from_string(str(value))
        return True
    except ValueError:
        return False


def _minor_amount(settlement: dict[str, Any], field: str) -> int | None:
    value = settlement.get(field)
    if value is not None:
        try:
            parsed = int(value)
            return parsed if parsed >= 0 else None
        except (TypeError, ValueError):
            return None
    decimal_field = field.removesuffix("_minor") + "_iat"
    try:
        parsed_decimal = Decimal(str(settlement.get(decimal_field)))
        if parsed_decimal < 0:
            return None
        return int(parsed_decimal * Decimal("1000000"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _find_settlement_authorization(cursor: Any, plan_id: str) -> Any:
    placeholder = db.qmark()
    cursor.execute(
        f"""SELECT * FROM protocol_settlement_authorizations
            WHERE plan_id = {placeholder}""",
        (plan_id,),
    )
    return cursor.fetchone()


def _public_settlement_authorization(row: Any) -> dict[str, Any]:
    record = dict(row)
    try:
        record["receipt_gate"] = json.loads(record.pop("receipt_gate_json"))
    except (TypeError, json.JSONDecodeError):
        record["receipt_gate"] = {}
    return {
        "status": "protocol_settlement_authorization_recorded",
        **record,
        "release_authorized": True,
        "effect": "authorization_only",
        "execution_enabled": False,
        "transaction_built": False,
        "simulation_performed": False,
        "transaction_signed": False,
        "transaction_broadcast": False,
        "funds_moved": False,
    }


def _evaluate_foundation_release(order_id: str) -> dict[str, Any]:
    # Imported lazily to keep this public registry independent from API startup.
    from iat.api.agent_b_api import authorize_settlement_release

    return authorize_settlement_release(order_id)


def _simulate_authorized_settlement(**kwargs: Any) -> dict[str, Any]:
    from iat.settlement_simulation import simulate_authorized_settlement

    return simulate_authorized_settlement(**kwargs)


def _find_settlement_simulation(cursor: Any, authorization_id: str) -> Any:
    placeholder = db.qmark()
    cursor.execute(
        f"""SELECT * FROM protocol_settlement_simulations
            WHERE authorization_id = {placeholder}""",
        (authorization_id,),
    )
    return cursor.fetchone()


def _public_settlement_simulation(row: Any) -> dict[str, Any]:
    return {
        "status": "protocol_settlement_simulation_recorded",
        **dict(row),
        "effect": "simulation_only",
        "execution_enabled": False,
        "unsigned_transaction_built": True,
        "serialized_transaction_disclosed": False,
        "transaction_signed": False,
        "transaction_broadcast": False,
        "funds_moved": False,
    }


def _lookup_journey(cursor: Any, evidence: dict[str, Any]) -> tuple[Any, Any]:
    placeholder = db.qmark()
    cursor.execute(
        f"""SELECT intent_decision_id, wallet, order_id
            FROM buyer_intent_decisions
            WHERE intent_decision_id = {placeholder} AND wallet = {placeholder}""",
        (evidence["evidence_id"], evidence["wallet_address"]),
    )
    intent = cursor.fetchone()
    if intent is None or not dict(intent).get("order_id"):
        return intent, None
    intent_record = dict(intent)
    cursor.execute(
        f"""SELECT quote_id, order_id, buyer_wallet, state, tx_signature
            FROM universal_checkout_quotes
            WHERE order_id = {placeholder} AND buyer_wallet = {placeholder}
            ORDER BY created_at DESC LIMIT 1""",
        (intent_record["order_id"], evidence["wallet_address"]),
    )
    return intent, cursor.fetchone()


def _validate_inbox_signature(receipt: dict[str, Any]) -> str:
    signature = receipt.get("inbox_signature")
    signer = receipt.get("inbox_signer")
    if not signature and not signer:
        return "not_configured"
    if not signature or not signer:
        return "invalid"
    try:
        valid = Signature.from_string(str(signature)).verify(
            Pubkey.from_string(str(signer)),
            str(receipt.get("sealed_payload") or "").encode(),
        )
    except ValueError:
        return "invalid"
    return "verified" if valid else "invalid"


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


@validation_router.post("/{evidence_receipt_id}")
def validate_delivery_binding(evidence_receipt_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        existing = _find_validation(cursor, evidence_receipt_id)
        if existing is not None:
            return _public_validation(existing)
        evidence_row = _find_receipt(cursor, evidence_receipt_id)
        if evidence_row is None:
            raise HTTPException(status_code=404, detail="protocol_evidence_not_found")
        evidence = dict(evidence_row)
        intent_row, quote_row = _lookup_journey(cursor, evidence)
    finally:
        db.release_conn(connection)

    if intent_row is None:
        raise HTTPException(status_code=409, detail="delivery_validation_intent_unavailable")
    intent = dict(intent_row)
    if quote_row is None:
        raise HTTPException(status_code=409, detail="delivery_validation_checkout_pending")
    quote_record = dict(quote_row)
    quote_id = str(quote_record.get("quote_id") or "")
    if quote_record.get("state") != "confirmed" or not quote_record.get("tx_signature"):
        raise HTTPException(status_code=409, detail="delivery_validation_checkout_pending")
    delivery = get_delivery(quote_id)
    receipt = get_delivery_receipt(quote_id)
    if not delivery or delivery.get("state") != "completed":
        raise HTTPException(status_code=409, detail="delivery_validation_execution_pending")
    if not receipt or receipt.get("state") not in {"delivered", "accepted"}:
        raise HTTPException(status_code=409, detail="delivery_validation_receipt_pending")
    sealed_payload = str(receipt.get("sealed_payload") or "")
    payload_digest = str(receipt.get("payload_digest") or "")
    digest_valid = bool(sealed_payload and len(payload_digest) == 64) and hashlib.sha256(
        sealed_payload.encode()
    ).hexdigest() == payload_digest
    signature_status = _validate_inbox_signature(receipt)
    opened = receipt.get("inbox_opened_at") is not None
    if not digest_valid or signature_status == "invalid":
        decision = "rejected_delivery_binding"
        reason = (
            "delivery_payload_digest_invalid"
            if not digest_valid
            else "delivery_payload_signature_invalid"
        )
    elif not opened:
        raise HTTPException(status_code=409, detail="delivery_validation_inbox_not_opened")
    else:
        decision = "verified_delivery_binding"
        reason = "protocol_checkout_execution_delivery_and_opening_bound"

    evaluated_at = _now()
    validation_payload = {
        "decision": decision,
        "evidence_id": evidence["evidence_id"],
        "evidence_receipt_id": evidence_receipt_id,
        "evaluated_at": evaluated_at,
        "inbox_signature_status": signature_status,
        "order_id": intent["order_id"],
        "payload_digest": payload_digest,
        "quote_id": quote_id,
        "reason": reason,
        "tx_signature": quote_record["tx_signature"],
        "wallet_address": evidence["wallet_address"],
    }
    validation_sha256 = hashlib.sha256(
        json.dumps(
            validation_payload, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    validation_id = "pdv_" + validation_sha256[:24]
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        placeholder = db.qmark()
        cursor.execute(
            f"""INSERT INTO protocol_delivery_validations (
                    validation_id, evidence_receipt_id, evidence_id, wallet_address,
                    order_id, quote_id, tx_signature, payload_digest,
                    inbox_signature_status, decision, reason, validation_sha256,
                    evaluated_at
                ) VALUES ({', '.join([placeholder] * 13)})""",
            (
                validation_id,
                evidence_receipt_id,
                evidence["evidence_id"],
                evidence["wallet_address"],
                intent["order_id"],
                quote_id,
                quote_record["tx_signature"],
                payload_digest,
                signature_status,
                decision,
                reason,
                validation_sha256,
                evaluated_at,
            ),
        )
        connection.commit()
        return _public_validation(_find_validation(cursor, evidence_receipt_id))
    finally:
        db.release_conn(connection)


@validation_router.get("/{evidence_receipt_id}")
def get_delivery_validation(evidence_receipt_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        record = _find_validation(connection.cursor(), evidence_receipt_id)
        if record is None:
            raise HTTPException(status_code=404, detail="delivery_validation_not_found")
        return _public_validation(record)
    finally:
        db.release_conn(connection)


@quality_router.post("/{delivery_validation_id}")
def validate_delivery_quality(delivery_validation_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        existing = _find_quality_validation(cursor, delivery_validation_id)
        if existing is not None:
            return _public_quality_validation(existing)
        placeholder = db.qmark()
        cursor.execute(
            f"""SELECT * FROM protocol_delivery_validations
                WHERE validation_id = {placeholder}""",
            (delivery_validation_id,),
        )
        delivery_row = cursor.fetchone()
        if delivery_row is None:
            raise HTTPException(status_code=404, detail="delivery_validation_not_found")
        delivery_validation = dict(delivery_row)
        if delivery_validation["decision"] != "verified_delivery_binding":
            raise HTTPException(status_code=409, detail="quality_validation_delivery_rejected")
        cursor.execute(
            f"""SELECT request_json FROM buyer_intent_decisions
                WHERE intent_decision_id = {placeholder}""",
            (delivery_validation["evidence_id"],),
        )
        intent_row = cursor.fetchone()
    finally:
        db.release_conn(connection)
    if intent_row is None:
        raise HTTPException(status_code=409, detail="quality_validation_intent_unavailable")
    try:
        request_payload = json.loads(dict(intent_row)["request_json"])
        raw_criteria = request_payload.get("acceptance_criteria")
        if not isinstance(raw_criteria, dict):
            raise HTTPException(status_code=409, detail="acceptance_criteria_not_declared")
        criteria = AcceptanceCriteria.model_validate(raw_criteria)
    except HTTPException:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail="acceptance_criteria_invalid") from exc

    receipt = get_delivery_receipt(str(delivery_validation["quote_id"]))
    if not receipt or not receipt.get("sealed_payload"):
        raise HTTPException(status_code=409, detail="quality_validation_payload_unavailable")
    try:
        result = json.loads(str(receipt["sealed_payload"]))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=409, detail="quality_validation_payload_invalid") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=409, detail="quality_validation_payload_invalid")
    evaluation = evaluate_acceptance(
        criteria,
        result,
        inbox_signature_status=str(delivery_validation["inbox_signature_status"]),
    )
    criteria_payload = criteria.model_dump()
    criteria_sha256 = hashlib.sha256(
        json.dumps(criteria_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evaluated_at = _now()
    public_facts = {
        "criteria_sha256": criteria_sha256,
        "decision": evaluation["decision"],
        "delivery_validation_id": delivery_validation_id,
        "evidence_id": delivery_validation["evidence_id"],
        "evidence_receipt_id": delivery_validation["evidence_receipt_id"],
        "evaluated_at": evaluated_at,
        "failed_count": evaluation["failed_count"],
        "passed_count": evaluation["passed_count"],
        "payload_digest": delivery_validation["payload_digest"],
    }
    quality_digest = hashlib.sha256(
        json.dumps(public_facts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    quality_id = "pqv_" + quality_digest[:24]
    checks_json = json.dumps(
        evaluation["checks"], sort_keys=True, separators=(",", ":")
    )
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        placeholder = db.qmark()
        cursor.execute(
            f"""INSERT INTO protocol_quality_validations (
                    quality_validation_id, delivery_validation_id,
                    evidence_receipt_id, evidence_id, decision, criteria_sha256,
                    payload_digest, checks_json, passed_count, failed_count,
                    quality_validation_sha256, evaluated_at
                ) VALUES ({', '.join([placeholder] * 12)})""",
            (
                quality_id,
                delivery_validation_id,
                delivery_validation["evidence_receipt_id"],
                delivery_validation["evidence_id"],
                evaluation["decision"],
                criteria_sha256,
                delivery_validation["payload_digest"],
                checks_json,
                evaluation["passed_count"],
                evaluation["failed_count"],
                quality_digest,
                evaluated_at,
            ),
        )
        connection.commit()
        return _public_quality_validation(
            _find_quality_validation(cursor, delivery_validation_id)
        )
    finally:
        db.release_conn(connection)


@quality_router.get("/{delivery_validation_id}")
def get_delivery_quality_validation(delivery_validation_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        record = _find_quality_validation(connection.cursor(), delivery_validation_id)
        if record is None:
            raise HTTPException(status_code=404, detail="quality_validation_not_found")
        return _public_quality_validation(record)
    finally:
        db.release_conn(connection)


@settlement_eligibility_router.post("/{quality_validation_id}")
def evaluate_settlement_eligibility(quality_validation_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        existing = _find_settlement_eligibility(cursor, quality_validation_id)
        if existing is not None:
            return _public_settlement_eligibility(existing)
        placeholder = db.qmark()
        cursor.execute(
            f"""SELECT q.*, d.order_id, d.quote_id
                FROM protocol_quality_validations q
                JOIN protocol_delivery_validations d
                  ON d.validation_id = q.delivery_validation_id
                WHERE q.quality_validation_id = {placeholder}""",
            (quality_validation_id,),
        )
        joined = cursor.fetchone()
    finally:
        db.release_conn(connection)
    if joined is None:
        raise HTTPException(status_code=404, detail="quality_validation_not_found")
    record = dict(joined)
    quality_decision = str(record["decision"])
    if quality_decision == "accepted_by_explicit_criteria":
        settlement = db.get_settlement_by_order_id_db(str(record["order_id"]))
        if not settlement:
            raise HTTPException(status_code=409, detail="settlement_allocation_pending")
        decision = "eligible_for_governed_release"
        reason = "explicit_quality_criteria_and_delivery_binding_passed"
        settlement_id = str(settlement.get("settlement_id") or "") or None
    elif quality_decision == "rejected_by_explicit_criteria":
        decision = "eligible_for_compensation_review"
        reason = "explicit_quality_criteria_failed_after_verified_delivery"
        settlement = db.get_settlement_by_order_id_db(str(record["order_id"]))
        settlement_id = (
            str(settlement.get("settlement_id") or "") or None
            if settlement
            else None
        )
    else:
        raise HTTPException(status_code=409, detail="quality_validation_not_terminal")

    evaluated_at = _now()
    policy_version = "settlement_eligibility_v1"
    eligibility_facts = {
        "decision": decision,
        "delivery_validation_id": record["delivery_validation_id"],
        "evidence_id": record["evidence_id"],
        "evidence_receipt_id": record["evidence_receipt_id"],
        "evaluated_at": evaluated_at,
        "order_id": record["order_id"],
        "policy_version": policy_version,
        "quality_validation_id": quality_validation_id,
        "quote_id": record["quote_id"],
        "reason": reason,
        "settlement_id": settlement_id,
    }
    eligibility_sha256 = hashlib.sha256(
        json.dumps(eligibility_facts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    eligibility_id = "pse_" + eligibility_sha256[:24]
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        placeholder = db.qmark()
        cursor.execute(
            f"""INSERT INTO protocol_settlement_eligibility (
                    eligibility_id, quality_validation_id, delivery_validation_id,
                    evidence_receipt_id, evidence_id, order_id, quote_id,
                    settlement_id, decision, reason, policy_version,
                    eligibility_sha256, evaluated_at
                ) VALUES ({', '.join([placeholder] * 13)})""",
            (
                eligibility_id,
                quality_validation_id,
                record["delivery_validation_id"],
                record["evidence_receipt_id"],
                record["evidence_id"],
                record["order_id"],
                record["quote_id"],
                settlement_id,
                decision,
                reason,
                policy_version,
                eligibility_sha256,
                evaluated_at,
            ),
        )
        connection.commit()
        return _public_settlement_eligibility(
            _find_settlement_eligibility(cursor, quality_validation_id)
        )
    finally:
        db.release_conn(connection)


@settlement_eligibility_router.get("/{quality_validation_id}")
def get_settlement_eligibility(quality_validation_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        record = _find_settlement_eligibility(connection.cursor(), quality_validation_id)
        if record is None:
            raise HTTPException(status_code=404, detail="settlement_eligibility_not_found")
        return _public_settlement_eligibility(record)
    finally:
        db.release_conn(connection)


@settlement_execution_plan_router.post("/{eligibility_id}")
def plan_settlement_execution(eligibility_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        existing = _find_settlement_execution_plan(cursor, eligibility_id)
        if existing is not None:
            return _public_settlement_execution_plan(existing)
        placeholder = db.qmark()
        cursor.execute(
            f"""SELECT * FROM protocol_settlement_eligibility
                WHERE eligibility_id = {placeholder}""",
            (eligibility_id,),
        )
        eligibility_row = cursor.fetchone()
    finally:
        db.release_conn(connection)
    if eligibility_row is None:
        raise HTTPException(status_code=404, detail="settlement_eligibility_not_found")
    eligibility = dict(eligibility_row)
    if eligibility["decision"] != "eligible_for_governed_release":
        raise HTTPException(
            status_code=409,
            detail="settlement_execution_plan_not_applicable",
        )
    settlement = db.get_settlement_by_order_id_db(str(eligibility["order_id"]))
    if not settlement or not settlement.get("settlement_id"):
        raise HTTPException(status_code=409, detail="settlement_allocation_unavailable")

    winner_wallet = settlement.get("winner_wallet")
    treasury_wallet = settlement.get("treasury_wallet")
    amounts = {
        name: _minor_amount(settlement, name)
        for name in (
            "gross_amount_minor",
            "protocol_commission_amount_minor",
            "seller_payout_amount_minor",
        )
    }
    blockers: list[str] = ["foundation_release_authorization_not_evaluated"]
    if not _valid_wallet(winner_wallet):
        blockers.append("winner_wallet_invalid")
    if not _valid_wallet(treasury_wallet):
        blockers.append("treasury_wallet_invalid")
    if any(value is None for value in amounts.values()):
        blockers.append("settlement_amount_invalid")
    elif (
        amounts["protocol_commission_amount_minor"]
        + amounts["seller_payout_amount_minor"]
        != amounts["gross_amount_minor"]
    ):
        blockers.append("settlement_amount_conservation_failed")
    receipt_gate = settlement_release_receipt_gate(str(eligibility["order_id"]))
    if not receipt_gate.get("release_allowed"):
        blockers.append(str(receipt_gate.get("reason") or "receipt_release_blocked"))

    evaluated_at = _now()
    policy_version = "settlement_execution_plan_v1"
    decision = "awaiting_governance_authorization"
    public_facts = {
        "blockers": sorted(set(blockers)),
        "decision": decision,
        "eligibility_id": eligibility_id,
        "evaluated_at": evaluated_at,
        "gross_amount_minor": amounts["gross_amount_minor"],
        "order_id": eligibility["order_id"],
        "policy_version": policy_version,
        "protocol_commission_amount_minor": amounts[
            "protocol_commission_amount_minor"
        ],
        "quality_validation_id": eligibility["quality_validation_id"],
        "receipt_gate": receipt_gate,
        "seller_payout_amount_minor": amounts["seller_payout_amount_minor"],
        "settlement_id": settlement["settlement_id"],
        "treasury_wallet": treasury_wallet,
        "winner_wallet": winner_wallet,
    }
    plan_sha256 = hashlib.sha256(
        json.dumps(public_facts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    plan_id = "psp_" + plan_sha256[:24]
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        placeholder = db.qmark()
        cursor.execute(
            f"""INSERT INTO protocol_settlement_execution_plans (
                    plan_id, eligibility_id, quality_validation_id, order_id,
                    settlement_id, winner_wallet, treasury_wallet,
                    gross_amount_minor, protocol_commission_amount_minor,
                    seller_payout_amount_minor, decision, blockers_json,
                    receipt_gate_json, policy_version, plan_sha256, evaluated_at
                ) VALUES ({', '.join([placeholder] * 16)})""",
            (
                plan_id,
                eligibility_id,
                eligibility["quality_validation_id"],
                eligibility["order_id"],
                settlement["settlement_id"],
                winner_wallet,
                treasury_wallet,
                amounts["gross_amount_minor"],
                amounts["protocol_commission_amount_minor"],
                amounts["seller_payout_amount_minor"],
                decision,
                json.dumps(public_facts["blockers"], separators=(",", ":")),
                json.dumps(receipt_gate, sort_keys=True, separators=(",", ":")),
                policy_version,
                plan_sha256,
                evaluated_at,
            ),
        )
        connection.commit()
        return _public_settlement_execution_plan(
            _find_settlement_execution_plan(cursor, eligibility_id)
        )
    finally:
        db.release_conn(connection)


@settlement_execution_plan_router.get("/{eligibility_id}")
def get_settlement_execution_plan(eligibility_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        record = _find_settlement_execution_plan(connection.cursor(), eligibility_id)
        if record is None:
            raise HTTPException(status_code=404, detail="settlement_execution_plan_not_found")
        return _public_settlement_execution_plan(record)
    finally:
        db.release_conn(connection)


@settlement_authorization_router.post("/{plan_id}")
def authorize_settlement_plan(plan_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        existing = _find_settlement_authorization(cursor, plan_id)
        if existing is not None:
            return _public_settlement_authorization(existing)
        placeholder = db.qmark()
        cursor.execute(
            f"""SELECT * FROM protocol_settlement_execution_plans
                WHERE plan_id = {placeholder}""",
            (plan_id,),
        )
        plan_row = cursor.fetchone()
    finally:
        db.release_conn(connection)
    if plan_row is None:
        raise HTTPException(status_code=404, detail="settlement_execution_plan_not_found")
    plan = dict(plan_row)
    try:
        blockers = json.loads(plan["blockers_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail="settlement_execution_plan_invalid") from exc
    structural_blockers = {
        blocker
        for blocker in blockers
        if blocker
        in {
            "winner_wallet_invalid",
            "treasury_wallet_invalid",
            "settlement_amount_invalid",
            "settlement_amount_conservation_failed",
        }
    }
    if not _valid_wallet(plan.get("winner_wallet")):
        structural_blockers.add("winner_wallet_invalid")
    if not _valid_wallet(plan.get("treasury_wallet")):
        structural_blockers.add("treasury_wallet_invalid")
    plan_amounts = (
        plan.get("gross_amount_minor"),
        plan.get("protocol_commission_amount_minor"),
        plan.get("seller_payout_amount_minor"),
    )
    if any(not isinstance(value, int) or value < 0 for value in plan_amounts):
        structural_blockers.add("settlement_amount_invalid")
    elif plan_amounts[1] + plan_amounts[2] != plan_amounts[0]:
        structural_blockers.add("settlement_amount_conservation_failed")
    if structural_blockers:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "settlement_execution_plan_structurally_blocked",
                "blockers": sorted(structural_blockers),
            },
        )

    authorization = _evaluate_foundation_release(str(plan["order_id"]))
    if not isinstance(authorization, dict):
        raise HTTPException(status_code=503, detail="foundation_authorization_unavailable")
    if authorization.get("release_authorized") is not True:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "foundation_release_not_authorized",
                "authorization_mode": authorization.get("authorization_mode"),
                "authorization_reason": authorization.get("authorization_reason"),
                "blockers": authorization.get("release_block_reasons") or [],
            },
        )
    if authorization.get("authorized_by") != "foundation":
        raise HTTPException(status_code=409, detail="foundation_authority_invalid")
    receipt_gate = authorization.get("final_delivery_receipt") or {}
    if receipt_gate.get("release_allowed") is not True:
        raise HTTPException(status_code=409, detail="final_delivery_receipt_not_accepted")

    financial_risk = authorization.get("financial_risk") or {}
    financial_risk_score = financial_risk.get(
        "release_risk_score", financial_risk.get("risk_score")
    )
    authorized_at = _now()
    policy_version = "settlement_authorization_v1"
    public_facts = {
        "authorization_mode": authorization.get("authorization_mode"),
        "authorization_reason": authorization.get("authorization_reason"),
        "authorized_at": authorized_at,
        "authorized_by": "foundation",
        "eligibility_id": plan["eligibility_id"],
        "financial_release_confidence": authorization.get(
            "financial_release_confidence"
        ),
        "financial_risk_score": financial_risk_score,
        "order_id": plan["order_id"],
        "plan_id": plan_id,
        "policy_version": policy_version,
        "receipt_gate": receipt_gate,
        "settlement_id": plan["settlement_id"],
    }
    authorization_sha256 = hashlib.sha256(
        json.dumps(public_facts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    authorization_id = "psa_" + authorization_sha256[:24]
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        placeholder = db.qmark()
        cursor.execute(
            f"""INSERT INTO protocol_settlement_authorizations (
                    authorization_id, plan_id, eligibility_id, order_id,
                    settlement_id, authorized_by, authorization_mode,
                    authorization_reason, financial_release_confidence,
                    financial_risk_score, receipt_gate_json, policy_version,
                    authorization_sha256, authorized_at
                ) VALUES ({', '.join([placeholder] * 14)})""",
            (
                authorization_id,
                plan_id,
                plan["eligibility_id"],
                plan["order_id"],
                plan["settlement_id"],
                "foundation",
                public_facts["authorization_mode"],
                public_facts["authorization_reason"],
                public_facts["financial_release_confidence"],
                financial_risk_score,
                json.dumps(receipt_gate, sort_keys=True, separators=(",", ":")),
                policy_version,
                authorization_sha256,
                authorized_at,
            ),
        )
        connection.commit()
        return _public_settlement_authorization(
            _find_settlement_authorization(cursor, plan_id)
        )
    finally:
        db.release_conn(connection)


@settlement_authorization_router.get("/{plan_id}")
def get_settlement_authorization(plan_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        record = _find_settlement_authorization(connection.cursor(), plan_id)
        if record is None:
            raise HTTPException(status_code=404, detail="settlement_authorization_not_found")
        return _public_settlement_authorization(record)
    finally:
        db.release_conn(connection)


@settlement_simulation_router.post("/{authorization_id}")
def simulate_settlement(authorization_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        existing = _find_settlement_simulation(cursor, authorization_id)
        if existing is not None:
            return _public_settlement_simulation(existing)
        placeholder = db.qmark()
        cursor.execute(
            f"""SELECT a.authorization_id, a.plan_id, a.settlement_id, a.order_id,
                       p.winner_wallet, p.treasury_wallet, p.gross_amount_minor,
                       p.protocol_commission_amount_minor,
                       p.seller_payout_amount_minor
                FROM protocol_settlement_authorizations a
                JOIN protocol_settlement_execution_plans p ON p.plan_id = a.plan_id
                WHERE a.authorization_id = {placeholder}""",
            (authorization_id,),
        )
        joined = cursor.fetchone()
    finally:
        db.release_conn(connection)
    if joined is None:
        raise HTTPException(status_code=404, detail="settlement_authorization_not_found")
    record = dict(joined)
    try:
        simulation = _simulate_authorized_settlement(
            authorization_id=authorization_id,
            settlement_id=str(record["settlement_id"]),
            order_id=str(record["order_id"]),
            winner_wallet=str(record["winner_wallet"]),
            treasury_wallet=str(record["treasury_wallet"]),
            gross_amount_minor=int(record["gross_amount_minor"]),
            commission_amount_minor=int(record["protocol_commission_amount_minor"]),
            seller_payout_amount_minor=int(record["seller_payout_amount_minor"]),
        )
    except Exception as exc:
        from iat.settlement_simulation import SettlementSimulationError

        if not isinstance(exc, SettlementSimulationError):
            raise
        code = str(exc)
        status_code = 503 if "rpc_" in code else 409
        raise HTTPException(status_code=status_code, detail=code) from exc
    if simulation.get("simulation_status") != "succeeded":
        raise HTTPException(status_code=409, detail="settlement_simulation_failed")
    if simulation.get("serialized_transaction_disclosed") is not False:
        raise HTTPException(status_code=409, detail="settlement_simulation_disclosure_invalid")

    simulated_at = _now()
    policy_version = "settlement_simulation_v1"
    public_facts = {
        key: simulation.get(key)
        for key in (
            "authorization_id",
            "cluster",
            "genesis_hash",
            "commitment",
            "token_program",
            "mint",
            "mint_decimals",
            "fee_payer",
            "escrow_authority",
            "source_token_account",
            "treasury_token_account",
            "winner_token_account",
            "gross_amount_minor",
            "protocol_commission_amount_minor",
            "seller_payout_amount_minor",
            "instruction_count",
            "required_signature_count",
            "unsigned_transaction_sha256",
            "simulation_logs_sha256",
            "units_consumed",
            "context_slot",
        )
    }
    public_facts.update(
        {
            "order_id": record["order_id"],
            "plan_id": record["plan_id"],
            "policy_version": policy_version,
            "settlement_id": record["settlement_id"],
            "simulated_at": simulated_at,
        }
    )
    simulation_sha256 = hashlib.sha256(
        json.dumps(public_facts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    simulation_id = "pss_" + simulation_sha256[:24]
    ordered_fields = (
        "cluster", "genesis_hash", "commitment", "token_program", "mint", "mint_decimals",
        "fee_payer", "escrow_authority", "source_token_account",
        "treasury_token_account", "winner_token_account", "gross_amount_minor",
        "protocol_commission_amount_minor", "seller_payout_amount_minor",
        "instruction_count", "required_signature_count",
        "unsigned_transaction_sha256", "simulation_logs_sha256",
        "units_consumed", "context_slot",
    )
    connection = db.get_conn()
    try:
        cursor = connection.cursor()
        placeholder = db.qmark()
        cursor.execute(
            f"""INSERT INTO protocol_settlement_simulations (
                    simulation_id, authorization_id, plan_id, settlement_id,
                    order_id, {', '.join(ordered_fields)}, policy_version,
                    simulation_sha256, simulated_at
                ) VALUES ({', '.join([placeholder] * 28)})""",
            (
                simulation_id,
                authorization_id,
                record["plan_id"],
                record["settlement_id"],
                record["order_id"],
                *(public_facts[field] for field in ordered_fields),
                policy_version,
                simulation_sha256,
                simulated_at,
            ),
        )
        connection.commit()
        return _public_settlement_simulation(
            _find_settlement_simulation(cursor, authorization_id)
        )
    finally:
        db.release_conn(connection)


@settlement_simulation_router.get("/{authorization_id}")
def get_settlement_simulation(authorization_id: str) -> dict[str, Any]:
    connection = db.get_conn()
    try:
        record = _find_settlement_simulation(connection.cursor(), authorization_id)
        if record is None:
            raise HTTPException(status_code=404, detail="settlement_simulation_not_found")
        return _public_settlement_simulation(record)
    finally:
        db.release_conn(connection)
