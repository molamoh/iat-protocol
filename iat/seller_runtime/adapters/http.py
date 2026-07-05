from typing import Dict, Any
import requests


def execute_http_adapter(
    seller_agent: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    endpoint = (
        seller_agent.get("endpoint")
        or seller_agent.get("url")
    )

    if not endpoint:
        return {
            "status": "http_endpoint_missing",
            "adapter": "http",
        }

    payload = {
        "execution_context": execution_context,
    }

    try:
        r = requests.post(
            endpoint.rstrip("/") + "/execute",
            json=payload,
            timeout=30,
        )

        return {
            "status": "ok" if r.status_code == 200 else "remote_error",
            "adapter": "http",
            "execution_mode": "remote_http",
            "status_code": r.status_code,
            "result": (
                r.json()
                if r.headers.get("content-type","").startswith("application/json")
                else {"body": r.text}
            ),
        }

    except Exception as e:
        return {
            "status": "http_exception",
            "adapter": "http",
            "error": str(e),
        }
