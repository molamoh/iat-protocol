"""Fail-closed GOIA partnership delivery dispatcher.

The lifecycle is implemented, but no network adapter is bundled or enabled.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any

from iat.goia.repository import (
    claim_partner_proposal,
    finish_partner_proposal_delivery,
    recover_stale_partner_deliveries,
    init_goia_tables,
)


DeliverySender = Callable[[dict[str, Any]], dict[str, Any]]


def delivery_enabled() -> bool:
    return (
        os.getenv("IAT_GOIA_PARTNERSHIP_DELIVERY_ENABLED", "false").strip().lower()
        == "true"
    )


def http_adapter_enabled() -> bool:
    return (
        os.getenv("IAT_GOIA_PARTNERSHIP_HTTP_ADAPTER_ENABLED", "false").strip().lower()
        == "true"
    )


def process_one_delivery(
    *,
    sender: DeliverySender | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if not delivery_enabled():
        return {
            "status": "disabled",
            "reason": "explicit_enable_required",
            "network_access_performed": False,
        }
    if sender is None and http_adapter_enabled():
        from iat.goia.partnership_http import send_partnership_proposal

        sender = send_partnership_proposal
    if sender is None:
        return {
            "status": "blocked",
            "reason": "delivery_adapter_not_configured",
            "network_access_performed": False,
        }
    recovery = recover_stale_partner_deliveries(now=now)
    proposal = claim_partner_proposal(now=now)
    if proposal is None:
        return {"status": "idle", "recovery": recovery}
    try:
        outcome = sender(proposal)
    except Exception:
        outcome = {
            "delivered": False,
            "retryable": True,
            "error_code": "delivery_adapter_exception",
        }
    result = finish_partner_proposal_delivery(
        proposal["proposal_id"],
        lease_token=proposal["lease_token"],
        delivered=bool(outcome.get("delivered")),
        retryable=bool(outcome.get("retryable")),
        error_code=str(outcome.get("error_code") or "delivery_failed"),
        receipt=outcome.get("receipt"),
        now=now,
    )
    return {
        "status": result["status"],
        "proposal_id": proposal["proposal_id"],
        "attempts": result["attempts"],
        "recovery": recovery,
        "network_access_performed": True,
    }


def main() -> int:
    if not delivery_enabled():
        print(json.dumps({"status": "disabled", "reason": "explicit_enable_required"}))
        return 0
    if not http_adapter_enabled():
        print(json.dumps({"status": "blocked", "reason": "http_adapter_not_enabled"}))
        return 2
    from iat.goia.partnership_http import (
        GOIAPartnershipTransportError,
        signing_public_key,
    )

    try:
        public_key = signing_public_key()
    except GOIAPartnershipTransportError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}))
        return 2
    init_goia_tables()
    interval = max(
        5,
        min(int(os.getenv("IAT_GOIA_PARTNERSHIP_DISPATCH_INTERVAL_SECONDS", "30")), 300),
    )
    print(json.dumps({"status": "started", "signing_public_key": public_key}))
    while True:
        print(json.dumps(process_one_delivery(), sort_keys=True))
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
