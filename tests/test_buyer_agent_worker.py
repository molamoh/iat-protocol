from iat.buyer_agent_worker import BuyerAgentWorker, BuyerAgentWorkerConfig


class Scheduler:
    def __init__(self):
        self.calls = []

    def run_due_once(self, *, limit):
        self.calls.append(limit)
        return [{"state": "waiting"}] if len(self.calls) == 1 else []


def test_worker_cycles_are_bounded_and_use_batch_limit():
    scheduler = Scheduler()
    waits = []
    worker = BuyerAgentWorker(
        scheduler,
        BuyerAgentWorkerConfig(interval_seconds=0.5, batch_limit=7),
        wait=lambda seconds: waits.append(seconds) or False,
    )
    result = worker.run(max_cycles=2)
    assert result == {"status": "stopped", "cycles": 2, "processed_jobs": 1}
    assert scheduler.calls == [7, 7]
    assert waits == [0.5]


def test_worker_honors_graceful_stop_between_cycles():
    scheduler = Scheduler()
    worker = None

    def stop_during_wait(_seconds):
        worker.stop()
        return True

    worker = BuyerAgentWorker(scheduler, wait=stop_during_wait)
    result = worker.run()
    assert result["cycles"] == 1
    assert scheduler.calls == [10]


def test_worker_configuration_is_bounded():
    config = BuyerAgentWorkerConfig.from_env(
        {
            "IAT_BUYER_WORKER_INTERVAL_SECONDS": "0.25",
            "IAT_BUYER_WORKER_BATCH_LIMIT": "100",
        }
    )
    assert config.interval_seconds == 0.25
    assert config.batch_limit == 100
