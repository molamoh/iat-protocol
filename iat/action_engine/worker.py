from typing import Any, Dict, Optional

from iat.action_engine.worker_manager import process_next_action_with_worker


def process_next_action(worker_id: Optional[str] = None) -> Dict[str, Any]:
    return process_next_action_with_worker(worker_id=worker_id)
