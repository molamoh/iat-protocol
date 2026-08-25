"""One-transition worker for the shared hosted buyer queue.

The worker owns queue leasing only. Wallets, session tokens and signer
credentials stay inside the runtime returned by ``runtime_resolver``.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from iat.autonomous_buyer import AutonomousBuyerError, AutonomousBuyerRunner
from iat.buyer_agent_scheduler import ACTIONABLE, HARD_STOP_ERRORS
from iat.hosted_buyer_jobs import (
    claim_hosted_buyer_job,
    finish_hosted_buyer_job,
)
from iat.wallet_adapters import WalletAdapterError


class HostedBuyerRuntimeUnavailable(RuntimeError):
    """The connector/runtime is temporarily unavailable."""


class HostedBuyerRuntimeResolver(Protocol):
    def resolve(self, buyer_agent_id: str) -> AutonomousBuyerRunner:
        """Return the isolated runner for one registered buyer agent."""


class HostedBuyerWorker:
    """Claim and execute at most one buyer transition per call."""

    def __init__(
        self,
        runtime_resolver: HostedBuyerRuntimeResolver,
        *,
        lease_seconds: int = 30,
        default_poll_seconds: int = 5,
    ) -> None:
        if lease_seconds < 15 or default_poll_seconds < 1:
            raise ValueError("hosted_worker_intervals_invalid")
        self.runtime_resolver = runtime_resolver
        self.lease_seconds = lease_seconds
        self.default_poll_seconds = default_poll_seconds

    def run_once(self, *, job_id: str | None = None, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time()) if now is None else int(now)
        job = claim_hosted_buyer_job(
            job_id=job_id, lease_seconds=self.lease_seconds, now=timestamp
        )
        if job.get("status") in {"empty", "retry"}:
            return job
        token = str(job.get("lease_token") or "")
        if not token:
            return {"status": "worker_lease_missing", "job_id": job.get("job_id")}
        try:
            runner = self.runtime_resolver.resolve(str(job["buyer_agent_id"]))
            decision_id = str(job["intent_decision_id"])
            lifecycle = runner.lifecycle(decision_id)
            action = str(lifecycle.get("next_action") or "")
            if action == "open_delivery_inbox":
                result = runner.open_result(decision_id)
                if result.get("status") == "buyer_result_not_ready":
                    return self._wait(job, token, action, self._poll_seconds(result), timestamp)
                return self._finish(job, token, "completed", action, None, timestamp)
            if action in ACTIONABLE:
                result = runner.step(decision_id)
                if result.get("status") == "buyer_signature_not_approved":
                    return self._finish(
                        job, token, "stopped", action, "buyer_signature_not_approved", timestamp
                    )
                return self._wait(job, token, action, self._poll_seconds(result), timestamp)
            if action == "wait_for_delivery":
                return self._wait(job, token, action, self._poll_seconds(lifecycle), timestamp)
            return self._finish(
                job, token, "stopped", action or None, "unsupported_or_unsafe_next_action", timestamp
            )
        except (HostedBuyerRuntimeUnavailable, AutonomousBuyerError, WalletAdapterError) as exc:
            code = str(getattr(exc, "code", "runtime_unavailable"))
            if code in HARD_STOP_ERRORS:
                return self._finish(job, token, "stopped", None, code, timestamp)
            return self._retry(job, token, code, timestamp)
        except Exception:
            return self._finish(job, token, "stopped", None, "unexpected_worker_failure", timestamp)

    def _wait(
        self, job: dict[str, Any], token: str, action: str, delay: int, now: int
    ) -> dict[str, Any]:
        if int(job.get("attempt_count") or 0) >= int(job.get("max_attempts") or 0):
            return self._finish(job, token, "stopped", action, "maximum_attempts_reached", now)
        return self._finish(job, token, "waiting", action, None, now, next_run_at=now + delay)

    def _retry(self, job: dict[str, Any], token: str, error: str, now: int) -> dict[str, Any]:
        delay = min(300, self.default_poll_seconds * (2 ** min(int(job.get("attempt_count") or 1) - 1, 5)))
        if int(job.get("attempt_count") or 0) >= int(job.get("max_attempts") or 0):
            return self._finish(job, token, "stopped", None, "maximum_attempts_reached", now)
        return self._finish(job, token, "waiting", None, error, now, next_run_at=now + delay)

    def _finish(
        self, job: dict[str, Any], token: str, state: str, action: str | None,
        error: str | None, now: int, *, next_run_at: int | None = None
    ) -> dict[str, Any]:
        return finish_hosted_buyer_job(
            job_id=str(job["job_id"]), lease_token=token, state=state,
            action=action, error=error, next_run_at=next_run_at, now=now
        )

    def _poll_seconds(self, payload: dict[str, Any]) -> int:
        try:
            value = int(payload.get("poll_after_seconds") or self.default_poll_seconds)
        except (TypeError, ValueError):
            value = self.default_poll_seconds
        return max(1, min(value, 300))
