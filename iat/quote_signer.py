"""Fail-closed Solana quote authorization for the isolated IAT signer."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction


class QuoteSigningRejected(RuntimeError):
    pass


def _pubkey(value: Any, label: str) -> Pubkey:
    try:
        return Pubkey.from_string(str(value or ""))
    except Exception as exc:
        raise QuoteSigningRejected(f"invalid_{label}") from exc


def _instruction_fingerprint(
    *,
    program_id: Pubkey,
    accounts: list[Pubkey],
    data: bytes,
) -> tuple[str, tuple[str, ...], bytes]:
    return str(program_id), tuple(str(value) for value in accounts), data


def _expected_instruction(value: Mapping[str, Any], label: str):
    try:
        program = _pubkey(value["program_id"], f"{label}_program")
        accounts = [_pubkey(item["address"], f"{label}_account") for item in value["accounts"]]
        data = base64.b64decode(str(value["data_base64"]), validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise QuoteSigningRejected(f"invalid_{label}_instruction") from exc
    return _instruction_fingerprint(program_id=program, accounts=accounts, data=data)


@dataclass(frozen=True)
class SigningResult:
    transaction_base64: str
    message_hash: str
    quote_authority: str
    expires_at: int


class LocalDevnetQuoteSigner:
    """Local-file backend allowed only for an explicitly enabled devnet canary."""

    def __init__(self, keypair: Keypair, *, cluster: str):
        if cluster != "devnet":
            raise QuoteSigningRejected("local_keypair_backend_devnet_only")
        self.keypair = keypair
        self.cluster = cluster

    @classmethod
    def from_file(cls, path: str, *, cluster: str) -> "LocalDevnetQuoteSigner":
        try:
            values = json.loads(Path(path).read_text(encoding="utf-8"))
            raw = bytes(values)
            if len(raw) != 64:
                raise ValueError("invalid keypair length")
            keypair = Keypair.from_bytes(raw)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QuoteSigningRejected("quote_signer_keypair_unavailable") from exc
        return cls(keypair, cluster=cluster)

    @property
    def pubkey(self) -> Pubkey:
        return self.keypair.pubkey()

    def sign(
        self,
        *,
        transaction_base64: str,
        instruction_plan: Mapping[str, Any],
        expires_at: int,
        now: int | None = None,
    ) -> SigningResult:
        current_time = int(time.time()) if now is None else int(now)
        if expires_at <= current_time:
            raise QuoteSigningRejected("quote_expired")
        if expires_at > current_time + 120:
            raise QuoteSigningRejected("quote_lifetime_too_long")
        try:
            plan_expires_at = int(instruction_plan["display"]["expires_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise QuoteSigningRejected("plan_expiration_missing") from exc
        if plan_expires_at != expires_at:
            raise QuoteSigningRejected("plan_expiration_mismatch")
        try:
            transaction = VersionedTransaction.from_bytes(
                base64.b64decode(transaction_base64, validate=True)
            )
        except Exception as exc:
            raise QuoteSigningRejected("invalid_serialized_transaction") from exc

        message = transaction.message
        if getattr(message, "address_table_lookups", ()):
            raise QuoteSigningRejected("address_lookup_tables_forbidden")
        if message.recent_blockhash == Hash.default():
            raise QuoteSigningRejected("recent_blockhash_required")

        keys = list(message.account_keys)
        signer_count = message.header.num_required_signatures
        signer_keys = keys[:signer_count]
        fee_payer = _pubkey(instruction_plan.get("fee_payer"), "fee_payer")
        quote_authority = _pubkey(
            instruction_plan.get("quote_authority"),
            "quote_authority",
        )
        if not keys or keys[0] != fee_payer:
            raise QuoteSigningRejected("fee_payer_mismatch")
        if quote_authority != self.pubkey or quote_authority not in signer_keys:
            raise QuoteSigningRejected("quote_authority_signer_mismatch")
        if instruction_plan.get("protocol_authorization_signature_required") is not True:
            raise QuoteSigningRejected("protocol_authorization_not_required")
        if instruction_plan.get("buyer_signature_required") is not True:
            raise QuoteSigningRejected("buyer_signature_not_required")
        if instruction_plan.get("network") != "solana":
            raise QuoteSigningRejected("invalid_network")

        allowed: dict[tuple[str, tuple[str, ...], bytes], str] = {}
        for field, label in (
            ("wallet_usage_prerequisite", "wallet_usage"),
            ("buyer_iat_account_prerequisite", "buyer_iat_account"),
            ("execute", "execute"),
        ):
            value = instruction_plan.get(field)
            if isinstance(value, Mapping):
                fingerprint = _expected_instruction(value, label)
                if fingerprint in allowed:
                    raise QuoteSigningRejected("duplicate_expected_instruction")
                allowed[fingerprint] = label
        if "execute" not in allowed.values():
            raise QuoteSigningRejected("execute_instruction_missing")

        observed: list[str] = []
        for compiled in message.instructions:
            try:
                program = keys[compiled.program_id_index]
                accounts = [keys[index] for index in compiled.accounts]
            except (IndexError, TypeError) as exc:
                raise QuoteSigningRejected("invalid_compiled_instruction") from exc
            fingerprint = _instruction_fingerprint(
                program_id=program,
                accounts=accounts,
                data=bytes(compiled.data),
            )
            label = allowed.get(fingerprint)
            if label is None:
                raise QuoteSigningRejected("unapproved_instruction")
            if label in observed:
                raise QuoteSigningRejected("duplicate_instruction")
            observed.append(label)
        if not observed or observed[-1] != "execute" or observed.count("execute") != 1:
            raise QuoteSigningRejected("execute_instruction_order_invalid")

        quote_index = signer_keys.index(quote_authority)
        signatures = list(transaction.signatures)
        if len(signatures) != signer_count:
            raise QuoteSigningRejected("signature_slot_mismatch")
        message_bytes = bytes(message)
        signatures[quote_index] = self.keypair.sign_message(message_bytes)
        signed = VersionedTransaction.populate(message, signatures)
        if not signatures[quote_index].verify(quote_authority, message_bytes):
            raise QuoteSigningRejected("quote_signature_verification_failed")
        return SigningResult(
            transaction_base64=base64.b64encode(bytes(signed)).decode(),
            message_hash=hashlib.sha256(message_bytes).hexdigest(),
            quote_authority=str(quote_authority),
            expires_at=expires_at,
        )


def verify_quote_authorization(
    *,
    original_transaction_base64: str,
    authorized_transaction_base64: str,
    quote_authority: str,
) -> str:
    """Verify that the signer changed only its own signature slot."""

    try:
        original = VersionedTransaction.from_bytes(
            base64.b64decode(original_transaction_base64, validate=True)
        )
        authorized = VersionedTransaction.from_bytes(
            base64.b64decode(authorized_transaction_base64, validate=True)
        )
    except Exception as exc:
        raise QuoteSigningRejected("invalid_authorized_transaction") from exc
    original_message = bytes(original.message)
    if bytes(authorized.message) != original_message:
        raise QuoteSigningRejected("authorized_message_mismatch")
    authority = _pubkey(quote_authority, "quote_authority")
    signer_count = original.message.header.num_required_signatures
    signer_keys = list(original.message.account_keys)[:signer_count]
    if authority not in signer_keys:
        raise QuoteSigningRejected("quote_authority_signer_mismatch")
    authority_index = signer_keys.index(authority)
    if len(original.signatures) != len(authorized.signatures):
        raise QuoteSigningRejected("signature_slot_mismatch")
    for index, (before, after) in enumerate(
        zip(original.signatures, authorized.signatures, strict=True)
    ):
        if index != authority_index and before != after:
            raise QuoteSigningRejected("non_authority_signature_modified")
    signature = authorized.signatures[authority_index]
    if not signature.verify(authority, original_message):
        raise QuoteSigningRejected("quote_signature_verification_failed")
    return hashlib.sha256(original_message).hexdigest()
