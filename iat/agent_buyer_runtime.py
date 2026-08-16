"""Environment-driven assembly for the non-custodial IAT buyer wallet sidecar."""

from __future__ import annotations

import hmac
import ipaddress
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlparse

from fastapi import FastAPI
from solders.pubkey import Pubkey

from iat.attested_wallet_signer import AttestedHTTPSDetachedSigner
from iat.solana_wallet_backend import SolanaRPCWalletBackend
from iat.wallet_sidecar import create_wallet_sidecar_app


REQUIRED_AGENT_BUYER_ENV = (
    "IAT_AGENT_WALLET_ADDRESS",
    "IAT_AGENT_SIGNER_URL",
    "IAT_AGENT_SIGNER_TOKEN",
    "IAT_WALLET_SIDECAR_TOKEN",
    "IAT_AGENT_MAX_USDC_MINOR",
    "IAT_AGENT_ALLOWED_PROGRAM_ID",
    "IAT_AGENT_ALLOWED_TREASURY_VAULT",
    "IAT_AGENT_ALLOWED_IAT_DESTINATION",
)


class AgentBuyerRuntimeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BoundedTransactionApproval:
    wallet_address: str
    maximum_usdc_minor: int
    allowed_program_id: str
    allowed_treasury_vault: str
    allowed_iat_destination: str
    cluster: str = "solana:devnet"

    def approve(self, review: Mapping[str, Any]) -> bool:
        payment = review.get("input")
        simulation = review.get("simulation")
        if not isinstance(payment, Mapping) or not isinstance(simulation, Mapping):
            return False
        try:
            amount = int(payment.get("amount_minor"))
            expires_at = int(review.get("expires_at"))
        except (TypeError, ValueError):
            return False
        now = int(time.time())
        checks = (
            review.get("cluster") == self.cluster,
            hmac.compare_digest(str(review.get("fee_payer") or ""), self.wallet_address),
            str(payment.get("asset") or "").upper() == "USDC",
            0 < amount <= self.maximum_usdc_minor,
            simulation.get("status") == "succeeded",
            now < expires_at <= now + 300,
            hmac.compare_digest(
                str(review.get("program_id") or ""), self.allowed_program_id
            ),
            hmac.compare_digest(
                str(review.get("treasury_vault") or ""), self.allowed_treasury_vault
            ),
            hmac.compare_digest(
                str(review.get("iat_destination") or ""), self.allowed_iat_destination
            ),
        )
        return all(checks)


@dataclass(frozen=True)
class AgentBuyerRuntimeConfig:
    wallet_address: str
    signer_url: str
    signer_token: str = field(repr=False)
    sidecar_token: str = field(repr=False)
    maximum_usdc_minor: int
    allowed_program_id: str
    allowed_treasury_vault: str
    allowed_iat_destination: str
    solana_rpc_url: str = "https://api.devnet.solana.com"
    cluster: str = "solana:devnet"

    def __post_init__(self):
        try:
            Pubkey.from_string(self.wallet_address)
            Pubkey.from_string(self.allowed_program_id)
            Pubkey.from_string(self.allowed_treasury_vault)
            Pubkey.from_string(self.allowed_iat_destination)
        except ValueError as exc:
            raise AgentBuyerRuntimeConfigError("invalid_solana_address") from exc
        if len(self.signer_token) < 16 or len(self.sidecar_token) < 16:
            raise AgentBuyerRuntimeConfigError("runtime_token_too_short")
        if not 1 <= self.maximum_usdc_minor <= 1_000_000_000_000:
            raise AgentBuyerRuntimeConfigError("maximum_usdc_minor_out_of_bounds")
        if self.cluster != "solana:devnet":
            raise AgentBuyerRuntimeConfigError("only_solana_devnet_is_supported")
        for name, value in (("signer_url", self.signer_url), ("solana_rpc_url", self.solana_rpc_url)):
            parsed = urlparse(value)
            try:
                loopback = bool(parsed.hostname) and ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                loopback = False
            if not parsed.hostname or (
                parsed.scheme != "https" and not (loopback and parsed.scheme == "http")
            ):
                raise AgentBuyerRuntimeConfigError(f"unsafe_{name}")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AgentBuyerRuntimeConfig":
        values = os.environ if env is None else env
        missing = [name for name in REQUIRED_AGENT_BUYER_ENV if not str(values.get(name) or "").strip()]
        if missing:
            raise AgentBuyerRuntimeConfigError(
                "missing_agent_buyer_configuration:" + ",".join(sorted(missing))
            )
        try:
            maximum = int(str(values["IAT_AGENT_MAX_USDC_MINOR"]))
        except ValueError as exc:
            raise AgentBuyerRuntimeConfigError("invalid_agent_max_usdc_minor") from exc
        return cls(
            wallet_address=str(values["IAT_AGENT_WALLET_ADDRESS"]).strip(),
            signer_url=str(values["IAT_AGENT_SIGNER_URL"]).strip(),
            signer_token=str(values["IAT_AGENT_SIGNER_TOKEN"]),
            sidecar_token=str(values["IAT_WALLET_SIDECAR_TOKEN"]),
            maximum_usdc_minor=maximum,
            allowed_program_id=str(values["IAT_AGENT_ALLOWED_PROGRAM_ID"]).strip(),
            allowed_treasury_vault=str(values["IAT_AGENT_ALLOWED_TREASURY_VAULT"]).strip(),
            allowed_iat_destination=str(values["IAT_AGENT_ALLOWED_IAT_DESTINATION"]).strip(),
            solana_rpc_url=str(
                values.get("IAT_AGENT_SOLANA_RPC_URL") or "https://api.devnet.solana.com"
            ).strip(),
            cluster=str(values.get("IAT_AGENT_SOLANA_CLUSTER") or "solana:devnet").strip(),
        )

    def approval(self) -> BoundedTransactionApproval:
        return BoundedTransactionApproval(
            wallet_address=self.wallet_address,
            maximum_usdc_minor=self.maximum_usdc_minor,
            allowed_program_id=self.allowed_program_id,
            allowed_treasury_vault=self.allowed_treasury_vault,
            allowed_iat_destination=self.allowed_iat_destination,
            cluster=self.cluster,
        )

    def create_sidecar_app(self) -> FastAPI:
        signer = AttestedHTTPSDetachedSigner(
            self.signer_url,
            wallet_address=self.wallet_address,
            auth_token=self.signer_token,
        )
        backend = SolanaRPCWalletBackend(
            signer=signer,
            approval=self.approval(),
            rpc_url=self.solana_rpc_url,
            cluster=self.cluster,
        )
        return create_wallet_sidecar_app(
            backend,
            auth_token=self.sidecar_token,
            allowed_clusters=(self.cluster,),
        )

    def diagnostic(self) -> dict[str, Any]:
        return {
            "status": "agent_buyer_sidecar_ready",
            "wallet_address": self.wallet_address,
            "cluster": self.cluster,
            "maximum_usdc_minor": self.maximum_usdc_minor,
            "signer_host": urlparse(self.signer_url).hostname,
            "rpc_host": urlparse(self.solana_rpc_url).hostname,
            "allowed_program_id": self.allowed_program_id,
            "allowed_treasury_vault": self.allowed_treasury_vault,
            "allowed_iat_destination": self.allowed_iat_destination,
            "signer_token_configured": True,
            "sidecar_token_configured": True,
            "private_key_configured": False,
        }


def diagnose_agent_buyer_runtime(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = os.environ if env is None else env
    missing = [name for name in REQUIRED_AGENT_BUYER_ENV if not str(values.get(name) or "").strip()]
    if missing:
        return {
            "status": "agent_buyer_sidecar_not_ready",
            "missing_configuration": sorted(missing),
            "private_key_required": False,
        }
    try:
        return AgentBuyerRuntimeConfig.from_env(values).diagnostic()
    except AgentBuyerRuntimeConfigError as exc:
        return {
            "status": "agent_buyer_sidecar_not_ready",
            "configuration_error": str(exc),
            "private_key_required": False,
        }


def create_wallet_sidecar_from_env() -> FastAPI:
    """Uvicorn factory: `uvicorn iat.agent_buyer_runtime:create_wallet_sidecar_from_env --factory`."""
    return AgentBuyerRuntimeConfig.from_env().create_sidecar_app()
