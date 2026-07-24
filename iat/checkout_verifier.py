"""Finalized Solana proof verification for hybrid checkout transactions."""

from __future__ import annotations

import base64
import hashlib
import struct
from dataclasses import dataclass
from typing import Any, Mapping

import requests
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction


PAYMENT_INTENT_DISCRIMINATOR = hashlib.sha256(
    b"account:PaymentIntent"
).digest()[:8]


class CheckoutVerificationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class PaymentIntentProof:
    config: str
    order_hash_hex: str
    quote_hash_hex: str
    buyer: str
    input_mint: str
    input_amount: int
    iat_amount: int
    nonce: int
    executed_at: int
    bump: int


def message_hash_from_transaction_base64(encoded: str) -> str:
    try:
        raw = base64.b64decode(encoded, validate=True)
        transaction = VersionedTransaction.from_bytes(raw)
    except Exception as exc:
        raise CheckoutVerificationError("invalid_serialized_transaction") from exc
    return hashlib.sha256(bytes(transaction.message)).hexdigest()


def decode_payment_intent(data: bytes) -> PaymentIntentProof:
    if len(data) != 201 or data[:8] != PAYMENT_INTENT_DISCRIMINATOR:
        raise CheckoutVerificationError("invalid_payment_intent_account")
    offset = 8

    def take(length: int) -> bytes:
        nonlocal offset
        value = data[offset : offset + length]
        offset += length
        return value

    config = Pubkey.from_bytes(take(32))
    order_hash = take(32)
    quote_hash = take(32)
    buyer = Pubkey.from_bytes(take(32))
    input_mint = Pubkey.from_bytes(take(32))
    input_amount, iat_amount, nonce, executed_at = struct.unpack(
        "<QQQq",
        take(32),
    )
    bump = take(1)[0]
    return PaymentIntentProof(
        config=str(config),
        order_hash_hex=order_hash.hex(),
        quote_hash_hex=quote_hash.hex(),
        buyer=str(buyer),
        input_mint=str(input_mint),
        input_amount=input_amount,
        iat_amount=iat_amount,
        nonce=nonce,
        executed_at=executed_at,
        bump=bump,
    )


class SolanaCheckoutVerifier:
    def __init__(
        self,
        rpc_url: str,
        *,
        timeout_seconds: float = 10.0,
        session: requests.Session | None = None,
    ):
        if not str(rpc_url).startswith("https://") and not str(rpc_url).startswith(
            "http://127.0.0.1"
        ):
            raise ValueError("rpc_url_must_be_https_or_localhost")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("invalid_rpc_timeout")
        self.rpc_url = rpc_url
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self._request_id = 0

    def verify(
        self,
        *,
        signature: str,
        route: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            expected_signature = Signature.from_string(signature)
        except Exception as exc:
            raise CheckoutVerificationError("invalid_transaction_signature") from exc
        self._require_finalized(signature)
        encoded, block_time = self._transaction(signature)
        try:
            transaction = VersionedTransaction.from_bytes(
                base64.b64decode(encoded, validate=True)
            )
        except Exception as exc:
            raise CheckoutVerificationError("invalid_rpc_transaction") from exc
        if not transaction.signatures or transaction.signatures[0] != expected_signature:
            raise CheckoutVerificationError("rpc_signature_mismatch")

        buyer = Pubkey.from_string(str(evidence.get("buyer_wallet") or ""))
        static_keys = list(transaction.message.account_keys)
        if not static_keys or static_keys[0] != buyer:
            raise CheckoutVerificationError("transaction_buyer_mismatch")

        normalized_route = str(route).lower()
        if normalized_route == "raydium":
            self._verify_raydium(transaction, evidence)
        elif normalized_route == "treasury":
            self._verify_treasury(transaction, evidence)
        else:
            raise CheckoutVerificationError("unsupported_checkout_route")
        return {
            "status": "confirmed",
            "route": normalized_route,
            "signature": signature,
            "block_time": block_time,
            "message_hash": hashlib.sha256(bytes(transaction.message)).hexdigest(),
            "finalized": True,
        }

    def _verify_raydium(
        self,
        transaction: VersionedTransaction,
        evidence: Mapping[str, Any],
    ) -> None:
        expected_hash = str(evidence.get("message_hash") or "")
        actual_hash = hashlib.sha256(bytes(transaction.message)).hexdigest()
        if len(expected_hash) != 64 or actual_hash != expected_hash:
            raise CheckoutVerificationError("raydium_message_hash_mismatch")

    def _verify_treasury(
        self,
        transaction: VersionedTransaction,
        evidence: Mapping[str, Any],
    ) -> None:
        program = Pubkey.from_string(str(evidence.get("program_id") or ""))
        quote_authority = Pubkey.from_string(
            str(evidence.get("quote_authority") or "")
        )
        payment_intent = Pubkey.from_string(
            str(evidence.get("payment_intent") or "")
        )
        static_keys = set(transaction.message.account_keys)
        signer_count = transaction.message.header.num_required_signatures
        signer_keys = set(list(transaction.message.account_keys)[:signer_count])
        if (
            program not in static_keys
            or payment_intent not in static_keys
            or quote_authority not in signer_keys
        ):
            raise CheckoutVerificationError("treasury_accounts_missing_from_transaction")
        account = self._account(str(payment_intent))
        if account.get("owner") != str(program) or account.get("executable") is True:
            raise CheckoutVerificationError("payment_intent_owner_mismatch")
        data_value = account.get("data")
        if (
            not isinstance(data_value, list)
            or len(data_value) < 2
            or data_value[1] != "base64"
        ):
            raise CheckoutVerificationError("invalid_payment_intent_encoding")
        try:
            proof = decode_payment_intent(base64.b64decode(data_value[0], validate=True))
        except ValueError as exc:
            raise CheckoutVerificationError("invalid_payment_intent_encoding") from exc
        expected = {
            "order_hash_hex": str(evidence.get("order_hash_hex") or ""),
            "quote_hash_hex": str(evidence.get("quote_hash_hex") or ""),
            "buyer": str(evidence.get("buyer_wallet") or ""),
            "input_mint": str(evidence.get("input_mint") or ""),
            "input_amount": int(evidence.get("input_amount") or 0),
            "iat_amount": int(evidence.get("iat_amount") or 0),
            "nonce": int(evidence.get("nonce") or 0),
        }
        actual = {
            "order_hash_hex": proof.order_hash_hex,
            "quote_hash_hex": proof.quote_hash_hex,
            "buyer": proof.buyer,
            "input_mint": proof.input_mint,
            "input_amount": proof.input_amount,
            "iat_amount": proof.iat_amount,
            "nonce": proof.nonce,
        }
        if actual != expected:
            raise CheckoutVerificationError("payment_intent_evidence_mismatch")

    def _require_finalized(self, signature: str) -> None:
        result = self._rpc(
            "getSignatureStatuses",
            [[signature], {"searchTransactionHistory": True}],
        )
        values = (result or {}).get("value") if isinstance(result, dict) else None
        status = values[0] if isinstance(values, list) and values else None
        if status is None:
            raise CheckoutVerificationError(
                "transaction_not_found",
                retryable=True,
            )
        if status.get("err") is not None:
            raise CheckoutVerificationError("transaction_failed")
        if status.get("confirmationStatus") != "finalized":
            raise CheckoutVerificationError(
                "transaction_not_finalized",
                retryable=True,
            )

    def _transaction(self, signature: str) -> tuple[str, int | None]:
        result = self._rpc(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "base64",
                    "commitment": "finalized",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        if not isinstance(result, dict):
            raise CheckoutVerificationError(
                "transaction_not_found",
                retryable=True,
            )
        transaction = result.get("transaction")
        if (
            not isinstance(transaction, list)
            or len(transaction) < 2
            or transaction[1] != "base64"
        ):
            raise CheckoutVerificationError("invalid_rpc_transaction")
        return str(transaction[0]), result.get("blockTime")

    def _account(self, address: str) -> dict[str, Any]:
        result = self._rpc(
            "getAccountInfo",
            [address, {"encoding": "base64", "commitment": "finalized"}],
        )
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise CheckoutVerificationError("payment_intent_not_found")
        return value

    def _rpc(self, method: str, params: list[Any]) -> Any:
        self._request_id += 1
        try:
            response = self.session.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": params,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CheckoutVerificationError(
                "solana_rpc_unavailable",
                retryable=True,
            ) from exc
        if not isinstance(payload, dict) or payload.get("error") is not None:
            raise CheckoutVerificationError(
                "solana_rpc_error",
                retryable=True,
            )
        return payload.get("result")
