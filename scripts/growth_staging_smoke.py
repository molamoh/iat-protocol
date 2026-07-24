"""Run one explicitly confirmed acquisition against an opted-in staging agent."""

from __future__ import annotations

import os
import sys

import requests


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def request(session, method: str, url: str, *, headers: dict, json: dict | None = None):
    response = session.request(method, url, headers=headers, json=json, timeout=30)
    if response.status_code >= 400:
        raise SystemExit(f"{method} {url} failed: HTTP {response.status_code} {response.text[:500]}")
    return response.json()


def main() -> int:
    if os.getenv("IAT_GROWTH_SMOKE_CONFIRM", "").lower() != "true":
        raise SystemExit(
            "Set IAT_GROWTH_SMOKE_CONFIRM=true only after the target agent opted in."
        )
    base_url = required("IAT_GROWTH_SMOKE_BASE_URL").rstrip("/")
    admin_key = required("IAT_ADMIN_API_KEY")
    prospect_url = required("IAT_GROWTH_SMOKE_PROSPECT_URL")
    headers = {"x-api-key": admin_key}
    session = requests.Session()

    prospect = request(
        session,
        "POST",
        f"{base_url}/admin/growth/prospects",
        headers=headers,
        json={
            "url": prospect_url,
            "name": "IAT opted-in staging prospect",
            "segment": "ai_agent",
            "source": "staging_smoke",
            "metadata": {
                "description": "AI agent API opted into an IAT protocol evaluation",
                "outreach_opt_in": True,
                "outreach_endpoint": prospect_url,
                "manifest_url": prospect_url,
            },
        },
    )
    prospect_id = prospect["prospect_id"]
    request(
        session,
        "POST",
        f"{base_url}/admin/growth/prospects/{prospect_id}/qualify",
        headers=headers,
    )
    campaign = request(
        session,
        "POST",
        f"{base_url}/admin/growth/campaigns",
        headers=headers,
        json={
            "name": "IAT staging acquisition smoke",
            "target_segment": "ai_agent",
            "min_score": 50,
            "daily_action_limit": 1,
            "policy": {
                "channel": "machine_webhook",
                "require_opt_in": True,
                "require_manual_action_approval": True,
                "variants": [
                    {"id": "control", "message": "Evaluate IAT through its no-funds sandbox."},
                    {"id": "commerce", "message": "Add governed machine commerce with IAT Protocol."},
                ],
            },
        },
    )
    campaign_id = campaign["campaign_id"]
    request(
        session,
        "POST",
        f"{base_url}/admin/growth/campaigns/{campaign_id}/status",
        headers=headers,
        json={"status": "active"},
    )
    action = request(
        session,
        "POST",
        f"{base_url}/admin/growth/actions/propose",
        headers=headers,
        json={"prospect_id": prospect_id, "campaign_id": campaign_id},
    )
    action_id = action["action_id"]
    request(
        session,
        "POST",
        f"{base_url}/admin/growth/actions/{action_id}/approve",
        headers=headers,
        json={
            "approved_by": "staging-smoke-operator",
            "reason": "Explicitly confirmed opted-in staging test",
        },
    )
    execution = request(
        session,
        "POST",
        f"{base_url}/admin/growth/actions/{action_id}/execute",
        headers=headers,
    )
    print(
        {
            "prospect_id": prospect_id,
            "campaign_id": campaign_id,
            "action_id": action_id,
            "execution": execution,
            "analytics_url": f"{base_url}/admin/growth/campaigns/{campaign_id}/analytics",
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
