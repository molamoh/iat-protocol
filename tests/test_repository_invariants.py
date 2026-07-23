from pathlib import Path

from iat.api.agent_b_api import app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_fastapi_routes_are_unique():
    routes = [
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    ]

    assert len(routes) == len(set(routes))


def test_docker_context_excludes_local_secrets_and_state():
    patterns = {
        line.strip()
        for line in (PROJECT_ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert {
        ".env.*",
        "*.db",
        "*keypair*.json",
        "escrow-wallet.json",
        "iat_wallets_v2.json",
        "archive/",
        "backups/",
    } <= patterns
