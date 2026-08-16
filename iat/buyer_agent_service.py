"""Local machine API exposing the bounded autonomous buyer journey."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from iat.agent_buyer_runtime import AgentBuyerRuntimeConfig, BoundedTransactionApproval
from iat.autonomous_buyer import AutonomousBuyerError, AutonomousBuyerRunner, BuyerRunnerPolicy
from iat.buyer_agent_scheduler import BuyerAgentScheduler
from iat.wallet_adapters import LocalWalletRPCAdapter, WalletAdapterError


class BuyerAgentIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=2, max_length=100)
    goal: str = Field(min_length=10, max_length=4_000)
    maximum_price: float = Field(gt=0, le=1_000_000_000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    strategy: str = Field(default="balanced", pattern="^(balanced|cheapest|fastest|safest|quality)$")
    required_capabilities: list[str] = Field(default_factory=list, max_length=20)
    auto_schedule: bool = True
    max_attempts: int = Field(default=100, ge=1, le=10_000)


class BuyerAgentScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=100, ge=1, le=10_000)


class BuyerAgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=100)


@dataclass(frozen=True)
class BuyerAgentServiceConfig:
    iat_api_url: str
    iat_access_token: str = field(repr=False)
    wallet_address: str
    sidecar_url: str
    sidecar_token: str = field(repr=False)
    service_token: str = field(repr=False)
    scheduler_database_path: str
    approval: BoundedTransactionApproval

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BuyerAgentServiceConfig":
        values = os.environ if env is None else env
        signing = AgentBuyerRuntimeConfig.from_env(values)
        required = ("IAT_API_URL", "IAT_WALLET_SESSION_TOKEN", "IAT_BUYER_AGENT_API_TOKEN")
        missing = [name for name in required if not str(values.get(name) or "").strip()]
        if missing:
            raise ValueError("missing_buyer_agent_configuration:" + ",".join(sorted(missing)))
        service_token = str(values["IAT_BUYER_AGENT_API_TOKEN"])
        access_token = str(values["IAT_WALLET_SESSION_TOKEN"])
        if len(service_token) < 16 or len(access_token) < 16:
            raise ValueError("buyer_agent_token_too_short")
        return cls(
            iat_api_url=str(values["IAT_API_URL"]).strip(),
            iat_access_token=access_token,
            wallet_address=signing.wallet_address,
            sidecar_url=str(values.get("IAT_WALLET_SIDECAR_URL") or "http://127.0.0.1:8787").strip(),
            sidecar_token=signing.sidecar_token,
            service_token=service_token,
            scheduler_database_path=str(
                values.get("IAT_BUYER_SCHEDULER_DB") or "iat-buyer-jobs.sqlite3"
            ).strip(),
            approval=signing.approval(),
        )

    def create_runner(self) -> AutonomousBuyerRunner:
        wallet = LocalWalletRPCAdapter(
            self.sidecar_url,
            wallet_address=self.wallet_address,
            auth_token=self.sidecar_token,
        )
        return AutonomousBuyerRunner(
            self.iat_api_url,
            access_token=self.iat_access_token,
            wallet=wallet,
            approval=self.approval,
            policy=BuyerRunnerPolicy(allowed_clusters=("solana:devnet",)),
        )


def create_buyer_agent_service(
    runner: AutonomousBuyerRunner,
    *,
    service_token: str,
    scheduler: BuyerAgentScheduler | None = None,
) -> FastAPI:
    if len(str(service_token)) < 16:
        raise ValueError("service_token is invalid")
    token = str(service_token)
    app = FastAPI(title="IAT Autonomous Buyer Agent", docs_url=None, redoc_url=None)

    def authenticate(authorization: str | None) -> None:
        scheme, separator, supplied = str(authorization or "").partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="invalid_buyer_agent_token")

    async def execute(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (AutonomousBuyerError, WalletAdapterError) as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc

    def require_scheduler() -> BuyerAgentScheduler:
        if scheduler is None:
            raise HTTPException(status_code=503, detail="buyer_agent_scheduler_not_configured")
        return scheduler

    @app.get("/health")
    async def health() -> dict[str, Any]:
        result = {
            "status": "ready",
            "wallet_address": runner.wallet.wallet_address,
            "cluster": list(runner.policy.allowed_clusters),
            "private_key_configured": False,
        }
        if scheduler is not None:
            result["scheduler"] = scheduler.summary()
        return result

    @app.post("/v1/intents")
    async def create_intent(
        req: BuyerAgentIntentRequest,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        authenticate(authorization)
        result = await execute(
            runner.create_intent,
            service=req.service,
            goal=req.goal,
            maximum_price=req.maximum_price,
            idempotency_key=req.idempotency_key,
            strategy=req.strategy,
            required_capabilities=req.required_capabilities,
        )
        decision_id = str(result.get("intent_decision_id") or "")
        if (
            req.auto_schedule
            and scheduler is not None
            and decision_id
            and result.get("status") == "buyer_intent_created"
        ):
            result["scheduler_job"] = scheduler.schedule(
                decision_id,
                max_attempts=req.max_attempts,
            )
        return result

    @app.post("/v1/intents/{intent_decision_id}/advance")
    async def advance(
        intent_decision_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        authenticate(authorization)
        return await execute(runner.step, intent_decision_id)

    @app.get("/v1/intents/{intent_decision_id}")
    async def lifecycle(
        intent_decision_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        authenticate(authorization)
        return await execute(runner.lifecycle, intent_decision_id)

    @app.get("/v1/intents/{intent_decision_id}/result")
    async def result(
        intent_decision_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        authenticate(authorization)
        return await execute(runner.open_result, intent_decision_id)

    @app.post("/v1/intents/{intent_decision_id}/schedule")
    async def schedule(
        intent_decision_id: str,
        req: BuyerAgentScheduleRequest,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        authenticate(authorization)
        return require_scheduler().schedule(intent_decision_id, max_attempts=req.max_attempts)

    @app.get("/v1/jobs/{intent_decision_id}")
    async def job(
        intent_decision_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        authenticate(authorization)
        try:
            return require_scheduler().get(intent_decision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc

    @app.post("/v1/scheduler/run-once")
    async def run_scheduler_once(
        req: BuyerAgentRunRequest,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        authenticate(authorization)
        jobs = require_scheduler().run_due_once(limit=req.limit)
        return {"status": "scheduler_cycle_completed", "processed": len(jobs), "jobs": jobs}

    return app


def create_buyer_agent_service_from_env() -> FastAPI:
    config = BuyerAgentServiceConfig.from_env()
    runner = config.create_runner()
    scheduler = BuyerAgentScheduler(runner, config.scheduler_database_path)
    return create_buyer_agent_service(
        runner,
        service_token=config.service_token,
        scheduler=scheduler,
    )
