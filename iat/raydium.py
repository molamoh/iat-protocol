"""Strict Raydium Trade API adapter for order-bound exact-output swaps."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import requests
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from spl.token.instructions import get_associated_token_address

from iat.checkout import RaydiumSnapshot


DEFAULT_API_URL = "https://transaction-v1.raydium.io"
POOL_API_URL = "https://api-v3.raydium.io"
COMPUTE_BUDGET_PROGRAM = Pubkey.from_string(
    "ComputeBudget111111111111111111111111111111"
)
SPL_TOKEN_PROGRAM = Pubkey.from_string(
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
)
TOKEN_2022_PROGRAM = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
)
ASSOCIATED_TOKEN_PROGRAM = Pubkey.from_string(
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")


class RaydiumError(RuntimeError):
    def __init__(self, code: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class RaydiumPolicy:
    api_url: str = DEFAULT_API_URL
    timeout_seconds: float = 8.0
    slippage_bps: int = 100
    max_price_impact_bps: int = 300
    max_input_amount_minor: int = 0
    allowed_pools: tuple[str, ...] = ()
    allowed_programs: tuple[str, ...] = ()
    compute_unit_price_micro_lamports: int = 50_000

    def validate(self) -> None:
        if self.api_url.rstrip("/") != DEFAULT_API_URL:
            raise RaydiumError("raydium_api_url_not_allowlisted")
        if not 0 < self.timeout_seconds <= 20:
            raise RaydiumError("invalid_raydium_timeout")
        if not 1 <= self.slippage_bps <= 500:
            raise RaydiumError("invalid_raydium_slippage")
        if not 0 <= self.max_price_impact_bps <= 1_000:
            raise RaydiumError("invalid_raydium_price_impact")
        if self.max_input_amount_minor <= 0:
            raise RaydiumError("invalid_raydium_input_cap")
        if len(self.allowed_pools) != 1:
            raise RaydiumError("exactly_one_raydium_pool_required")
        if not 1 <= len(self.allowed_programs) <= 4:
            raise RaydiumError("invalid_raydium_program_allowlist")
        for value in (*self.allowed_pools, *self.allowed_programs):
            _pubkey(value, "raydium_allowlist")


@dataclass(frozen=True)
class ValidatedRaydiumQuote:
    snapshot: RaydiumSnapshot
    response: dict[str, Any]


def _pubkey(value: Any, field: str) -> Pubkey:
    try:
        return Pubkey.from_string(str(value or "").strip())
    except Exception as exc:
        raise RaydiumError(f"invalid_{field}") from exc


def _positive_int(value: Any, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise RaydiumError(f"invalid_{field}") from exc
    if parsed <= 0:
        raise RaydiumError(f"invalid_{field}")
    return parsed


def _impact_bps(value: Any) -> int:
    try:
        percent = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RaydiumError("invalid_raydium_price_impact") from exc
    if not percent.is_finite() or percent < 0:
        raise RaydiumError("invalid_raydium_price_impact")
    return int((percent * Decimal(100)).to_integral_value())


def _is_writable(message: Message, index: int) -> bool:
    header = message.header
    required = header.num_required_signatures
    if index < required:
        return index < required - header.num_readonly_signed_accounts
    return index < len(message.account_keys) - header.num_readonly_unsigned_accounts


class RaydiumClient:
    def __init__(
        self,
        policy: RaydiumPolicy,
        *,
        session: requests.Session | None = None,
        clock=time.time,
    ):
        policy.validate()
        self.policy = policy
        self.session = session or requests.Session()
        self.clock = clock

    def fetch_pool_liquidity_usd(
        self,
        *,
        input_mint: str,
        output_mint: str,
    ) -> Decimal:
        input_key = _pubkey(input_mint, "input_mint")
        output_key = _pubkey(output_mint, "output_mint")
        pool_id = self.policy.allowed_pools[0]
        response = self._request(
            "GET",
            "/pools/info/ids",
            base_url=POOL_API_URL,
            params={"ids": pool_id},
        )
        data = self._validated_envelope(response, "raydium_pool_lookup_failed")
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise RaydiumError("invalid_raydium_pool_response")
        pool = data[0]
        if pool.get("id") != pool_id:
            raise RaydiumError("raydium_pool_not_allowlisted")
        if str(pool.get("programId") or "") not in self.policy.allowed_programs:
            raise RaydiumError("raydium_pool_program_not_allowlisted")
        mints = {
            str((pool.get("mintA") or {}).get("address") or ""),
            str((pool.get("mintB") or {}).get("address") or ""),
        }
        if mints != {str(input_key), str(output_key)}:
            raise RaydiumError("raydium_pool_mint_mismatch")
        try:
            liquidity = Decimal(str(pool.get("tvl")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RaydiumError("invalid_raydium_pool_liquidity") from exc
        if not liquidity.is_finite() or liquidity <= 0:
            raise RaydiumError("invalid_raydium_pool_liquidity")
        return liquidity

    def quote_exact_output(
        self,
        *,
        input_mint: str,
        output_mint: str,
        output_amount_minor: int,
        input_decimals: int,
        output_decimals: int,
        pool_liquidity_usd: Decimal,
    ) -> ValidatedRaydiumQuote:
        input_key = _pubkey(input_mint, "input_mint")
        output_key = _pubkey(output_mint, "output_mint")
        if input_key == output_key:
            raise RaydiumError("raydium_mints_must_differ")
        amount = _positive_int(output_amount_minor, "raydium_output_amount")
        if not 0 <= input_decimals <= 18 or not 0 <= output_decimals <= 18:
            raise RaydiumError("invalid_raydium_decimals")
        response = self._request(
            "GET",
            "/compute/swap-base-out",
            params={
                "inputMint": str(input_key),
                "outputMint": str(output_key),
                "amount": str(amount),
                "slippageBps": str(self.policy.slippage_bps),
                "txVersion": "LEGACY",
            },
        )
        data = self._validated_envelope(response, "raydium_quote_failed")
        if str(data.get("swapType") or "").lower() not in {"baseout", "base_out"}:
            raise RaydiumError("unexpected_raydium_swap_type")
        if data.get("inputMint") != str(input_key) or data.get("outputMint") != str(output_key):
            raise RaydiumError("raydium_quote_mint_mismatch")
        input_amount = _positive_int(data.get("inputAmount"), "raydium_input_amount")
        output_amount = _positive_int(data.get("outputAmount"), "raydium_output_amount")
        maximum_input = _positive_int(
            data.get("otherAmountThreshold"),
            "raydium_maximum_input",
        )
        if output_amount != amount:
            raise RaydiumError("raydium_exact_output_mismatch")
        if maximum_input > self.policy.max_input_amount_minor:
            raise RaydiumError("raydium_input_cap_exceeded")
        if input_amount > maximum_input:
            raise RaydiumError("raydium_threshold_below_input")

        route = data.get("routePlan")
        if not isinstance(route, list) or len(route) != 1:
            raise RaydiumError("raydium_single_hop_required")
        pool_id = str(route[0].get("poolId") or "")
        if pool_id not in self.policy.allowed_pools:
            raise RaydiumError("raydium_pool_not_allowlisted")
        if (
            route[0].get("inputMint") != str(input_key)
            or route[0].get("outputMint") != str(output_key)
        ):
            raise RaydiumError("raydium_route_mint_mismatch")
        impact_bps = _impact_bps(data.get("priceImpactPct"))
        if impact_bps > self.policy.max_price_impact_bps:
            raise RaydiumError("raydium_price_impact_exceeded")

        return ValidatedRaydiumQuote(
            snapshot=RaydiumSnapshot(
                input_amount=Decimal(maximum_input) / (Decimal(10) ** input_decimals),
                output_iat=Decimal(output_amount) / (Decimal(10) ** output_decimals),
                price_impact_bps=impact_bps,
                pool_liquidity_usd=pool_liquidity_usd,
                pool_id=pool_id,
                observed_at=int(self.clock()),
            ),
            response=response,
        )

    def build_exact_output_transaction(
        self,
        *,
        quote_response: Mapping[str, Any],
        buyer_wallet: str,
        input_account: str,
        settlement_escrow: str,
        expected_input_mint: str,
        expected_output_mint: str,
        expected_output_amount_minor: int,
    ) -> dict[str, Any]:
        buyer = _pubkey(buyer_wallet, "buyer_wallet")
        buyer_input = _pubkey(input_account, "input_account")
        escrow = _pubkey(settlement_escrow, "settlement_escrow")
        input_mint = _pubkey(expected_input_mint, "input_mint")
        output_mint = _pubkey(expected_output_mint, "output_mint")
        quote_data = self._validated_envelope(
            dict(quote_response),
            "raydium_quote_failed",
        )
        if not isinstance(quote_data, dict):
            raise RaydiumError("invalid_raydium_response")
        if (
            quote_data.get("inputMint") != str(input_mint)
            or quote_data.get("outputMint") != str(output_mint)
        ):
            raise RaydiumError("raydium_quote_mint_mismatch")
        if _positive_int(
            quote_data.get("outputAmount"),
            "raydium_output_amount",
        ) != _positive_int(expected_output_amount_minor, "raydium_output_amount"):
            raise RaydiumError("raydium_exact_output_mismatch")
        response = self._request(
            "POST",
            "/transaction/swap-base-out",
            json={
                "wallet": str(buyer),
                "swapResponse": dict(quote_response),
                "txVersion": "LEGACY",
                "computeUnitPriceMicroLamports": str(
                    self.policy.compute_unit_price_micro_lamports
                ),
                "wrapSol": False,
                "unwrapSol": False,
                "inputAccount": str(buyer_input),
                "outputAccount": str(escrow),
            },
        )
        data = self._validated_envelope(response, "raydium_transaction_build_failed")
        entries = data if isinstance(data, list) else [data]
        if len(entries) != 1 or not isinstance(entries[0], dict):
            raise RaydiumError("raydium_atomic_single_transaction_required")
        encoded = entries[0].get("transaction")
        if not isinstance(encoded, str) or len(encoded) > 20_000:
            raise RaydiumError("invalid_raydium_serialized_transaction")
        try:
            raw = base64.b64decode(encoded, validate=True)
            transaction = VersionedTransaction.from_bytes(raw)
        except Exception as exc:
            raise RaydiumError("invalid_raydium_serialized_transaction") from exc
        self._validate_legacy_transaction(
            transaction=transaction,
            buyer=buyer,
            buyer_input=buyer_input,
            settlement_escrow=escrow,
            input_mint=input_mint,
            output_mint=output_mint,
        )
        return {
            "provider": "raydium_trade_api_v2",
            "transaction_version": "LEGACY",
            "transaction_base64": encoded,
            "transaction_count": 1,
            "fee_payer": str(buyer),
            "buyer_signature_required": True,
            "server_signature_required": False,
            "simulation_required": True,
            "input_account": str(buyer_input),
            "output_account": str(escrow),
            "output_to_buyer_wallet": False,
        }

    def _validate_legacy_transaction(
        self,
        *,
        transaction: VersionedTransaction,
        buyer: Pubkey,
        buyer_input: Pubkey,
        settlement_escrow: Pubkey,
        input_mint: Pubkey,
        output_mint: Pubkey,
    ) -> None:
        message = transaction.message
        if not isinstance(message, Message):
            raise RaydiumError("raydium_legacy_transaction_required")
        keys = list(message.account_keys)
        required = {buyer, buyer_input, settlement_escrow, input_mint, output_mint}
        if not required.issubset(set(keys)):
            raise RaydiumError("raydium_transaction_account_mismatch")
        if not keys or keys[0] != buyer:
            raise RaydiumError("raydium_fee_payer_mismatch")
        if message.header.num_required_signatures != 1:
            raise RaydiumError("raydium_unexpected_signers")
        if len(transaction.signatures) != 1 or transaction.signatures[0] != Signature.default():
            raise RaydiumError("raydium_transaction_must_be_unsigned")
        if (
            not _is_writable(message, keys.index(buyer_input))
            or not _is_writable(message, keys.index(settlement_escrow))
        ):
            raise RaydiumError("raydium_payment_accounts_must_be_writable")
        buyer_iat_account = get_associated_token_address(buyer, output_mint)
        if buyer_iat_account in keys:
            raise RaydiumError("raydium_buyer_iat_destination_forbidden")

        allowed_raydium = {_pubkey(value, "raydium_program") for value in self.policy.allowed_programs}
        raydium_instruction_count = 0
        for instruction in message.instructions:
            try:
                program = keys[instruction.program_id_index]
            except IndexError as exc:
                raise RaydiumError("invalid_raydium_program_index") from exc
            if program in allowed_raydium:
                raydium_instruction_count += 1
            elif program != COMPUTE_BUDGET_PROGRAM:
                raise RaydiumError(
                    "raydium_transaction_program_not_allowlisted",
                    details={"program": str(program)},
                )
        if raydium_instruction_count != 1:
            raise RaydiumError("exactly_one_raydium_instruction_required")

    def _request(
        self,
        method: str,
        path: str,
        *,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                (base_url or self.policy.api_url).rstrip("/") + path,
                timeout=self.policy.timeout_seconds,
                headers={"Accept": "application/json"},
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RaydiumError("raydium_transport_error") from exc
        if not isinstance(payload, dict):
            raise RaydiumError("invalid_raydium_response")
        return payload

    @staticmethod
    def _validated_envelope(response: dict[str, Any], code: str) -> Any:
        if response.get("success") is not True:
            raise RaydiumError(code)
        data = response.get("data")
        if not isinstance(data, (dict, list)):
            raise RaydiumError("invalid_raydium_response")
        return data
