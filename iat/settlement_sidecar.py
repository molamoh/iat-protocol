"""Local settlement sidecar mounted inside the existing Render service."""

from __future__ import annotations

import base64
import os
from typing import Any, Mapping

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from iat.solana_wallet_backend import SolanaRPCWalletBackend
from iat.settlement_signing_policy import BoundedSettlementApproval
from iat.transfer import load_keypair
from iat.wallet_sidecar import create_wallet_sidecar_app


class LocalEscrowDetachedSigner:
    """Sidecar-only signer backed by the existing Render escrow secret."""

    def __init__(self, keypair: Keypair):
        self._keypair = keypair

    @property
    def wallet_address(self) -> str:
        return str(self._keypair.pubkey())

    def sign_transaction(self, transaction_base64: str, review: Mapping[str, Any]) -> str:
        try:
            raw = base64.b64decode(str(transaction_base64), validate=True)
            transaction = VersionedTransaction.from_bytes(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("settlement_transaction_invalid") from exc
        required = list(transaction.message.account_keys)[
            : int(transaction.message.header.num_required_signatures)
        ]
        if self._keypair.pubkey() not in required:
            raise RuntimeError("settlement_signer_not_required")
        index = required.index(self._keypair.pubkey())
        signatures = list(transaction.signatures)
        if signatures[index] != Signature.default():
            raise RuntimeError("settlement_signature_slot_not_empty")
        signatures[index] = self._keypair.sign_message(bytes(transaction.message))
        signed = VersionedTransaction.populate(transaction.message, signatures)
        return base64.b64encode(bytes(signed)).decode()

    def sign_evidence(self, **_kwargs: Any) -> Mapping[str, Any]:
        raise RuntimeError("settlement_evidence_signing_not_supported")


def _required_env() -> tuple[str, str, str, str, str] | None:
    keypair = (
        os.getenv("IAT_ESCROW_KEYPAIR_JSON")
        or os.getenv("IAT_ESCROW_KEYPAIR_PATH")
    )
    escrow_wallet = os.getenv("IAT_ESCROW_WALLET", "").strip()
    treasury_wallet = os.getenv("IAT_PROTOCOL_TREASURY_WALLET", "").strip()
    token = os.getenv("IAT_SETTLEMENT_WALLET_SIDECAR_TOKEN", "")
    maximum = os.getenv("IAT_SETTLEMENT_MAX_GROSS_IAT_MINOR", "100000000")
    if not keypair or not escrow_wallet or not treasury_wallet or len(token) < 16:
        return None
    return str(keypair), escrow_wallet, treasury_wallet, token, maximum


def create_settlement_sidecar_app_from_env():
    values = _required_env()
    if values is None:
        return None
    keypair_input, escrow_wallet, treasury_wallet, token, maximum = values
    try:
        keypair = load_keypair(keypair_input)
        if str(keypair.pubkey()) != escrow_wallet:
            return None
        policy = BoundedSettlementApproval(
            escrow_wallet=escrow_wallet,
            treasury_wallet=treasury_wallet,
            maximum_gross_iat_minor=int(maximum),
        )
        backend = SolanaRPCWalletBackend(
            signer=LocalEscrowDetachedSigner(keypair),
            approval=policy,
            rpc_url=(
                os.getenv("IAT_SETTLEMENT_SIMULATION_RPC_URL")
                or "https://api.devnet.solana.com"
            ),
            cluster="solana:devnet",
        )
        return create_wallet_sidecar_app(
            backend,
            auth_token=token,
            allowed_clusters=("solana:devnet",),
        )
    except (OSError, TypeError, ValueError, RuntimeError):
        return None


def settlement_sidecar_diagnostic() -> dict[str, Any]:
    keypair_input = (
        os.getenv("IAT_ESCROW_KEYPAIR_JSON")
        or os.getenv("IAT_ESCROW_KEYPAIR_PATH")
    )
    escrow_wallet = os.getenv("IAT_ESCROW_WALLET", "").strip()
    treasury_wallet = os.getenv("IAT_PROTOCOL_TREASURY_WALLET", "").strip()
    token_configured = len(os.getenv("IAT_SETTLEMENT_WALLET_SIDECAR_TOKEN", "")) >= 16
    missing = [
        name for name, value in (
            ("IAT_ESCROW_KEYPAIR_JSON_OR_PATH", keypair_input),
            ("IAT_ESCROW_WALLET", escrow_wallet),
            ("IAT_PROTOCOL_TREASURY_WALLET", treasury_wallet),
        ) if not str(value or "").strip()
    ]
    keypair_status = "not_checked"
    wallet_match = False
    if keypair_input:
        try:
            keypair = load_keypair(keypair_input)
            keypair_status = "loaded"
            wallet_match = str(keypair.pubkey()) == escrow_wallet
        except Exception:
            keypair_status = "unavailable_or_invalid"
    treasury_status = "valid"
    if treasury_wallet:
        try:
            Pubkey.from_string(treasury_wallet)
        except ValueError:
            treasury_status = "invalid"
    if not token_configured:
        missing.append("IAT_SETTLEMENT_WALLET_SIDECAR_TOKEN")
    if keypair_status != "loaded":
        missing.append("escrow_keypair_load")
    elif not wallet_match:
        missing.append("escrow_wallet_keypair_mismatch")
    if treasury_status != "valid":
        missing.append("treasury_wallet_invalid")
    return {
        "status": "settlement_sidecar_ready" if not missing else "settlement_sidecar_not_ready",
        "local_only": True,
        "public_url_required": False,
        "private_key_returned": False,
        "wallet_configured": bool(escrow_wallet),
        "token_configured": token_configured,
        "keypair_status": keypair_status,
        "wallet_matches_keypair": wallet_match,
        "treasury_status": treasury_status,
        "missing_checks": sorted(set(missing)),
    }
