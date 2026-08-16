"""Supervisable worker for persistent autonomous buyer jobs."""

from __future__ import annotations

import os
import signal
import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from iat.buyer_agent_scheduler import BuyerAgentScheduler
from iat.buyer_agent_service import BuyerAgentServiceConfig


@dataclass(frozen=True)
class BuyerAgentWorkerConfig:
    interval_seconds: float = 2.0
    batch_limit: int = 10

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BuyerAgentWorkerConfig":
        values = os.environ if env is None else env
        interval = float(values.get("IAT_BUYER_WORKER_INTERVAL_SECONDS") or 2)
        limit = int(values.get("IAT_BUYER_WORKER_BATCH_LIMIT") or 10)
        if not 0.25 <= interval <= 60:
            raise ValueError("buyer_worker_interval_invalid")
        if not 1 <= limit <= 100:
            raise ValueError("buyer_worker_batch_limit_invalid")
        return cls(interval_seconds=interval, batch_limit=limit)


class BuyerAgentWorker:
    """Wake the scheduler periodically; every wake remains independently bounded."""

    def __init__(
        self,
        scheduler: BuyerAgentScheduler,
        config: BuyerAgentWorkerConfig | None = None,
        *,
        wait: Callable[[float], bool] | None = None,
    ):
        self.scheduler = scheduler
        self.config = config or BuyerAgentWorkerConfig()
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait

    def stop(self) -> None:
        self._stop.set()

    def run(self, *, max_cycles: int | None = None) -> dict[str, int | str]:
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("buyer_worker_max_cycles_invalid")
        cycles = 0
        processed = 0
        while not self._stop.is_set() and (max_cycles is None or cycles < max_cycles):
            jobs = self.scheduler.run_due_once(limit=self.config.batch_limit)
            cycles += 1
            processed += len(jobs)
            if max_cycles is not None and cycles >= max_cycles:
                break
            if self._wait(self.config.interval_seconds):
                break
        return {
            "status": "stopped",
            "cycles": cycles,
            "processed_jobs": processed,
        }


def main() -> None:
    service_config = BuyerAgentServiceConfig.from_env()
    worker_config = BuyerAgentWorkerConfig.from_env()
    runner = service_config.create_runner()
    scheduler = BuyerAgentScheduler(runner, service_config.scheduler_database_path)
    worker = BuyerAgentWorker(scheduler, worker_config)

    def request_stop(_signum, _frame) -> None:
        worker.stop()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    worker.run()


if __name__ == "__main__":
    main()
