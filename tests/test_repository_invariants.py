import os
from pathlib import Path
import subprocess
import sys

from iat.api.agent_b_api import app
from iat.config import DEFAULT_IAT_TOKEN_ADDRESS, IAT_TOKEN_ADDRESS
from iat.onchain import IAT_MINT as ONCHAIN_IAT_MINT
from iat.transfer import IAT_MINT as TRANSFER_IAT_MINT


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_iat_mint_has_one_canonical_source_of_truth():
    assert DEFAULT_IAT_TOKEN_ADDRESS == "3vRGo1VpGbZH67Ur2UG7VNUqSqQyApLQEcCxgnqK4f4Z"
    assert IAT_TOKEN_ADDRESS == DEFAULT_IAT_TOKEN_ADDRESS
    assert ONCHAIN_IAT_MINT == IAT_TOKEN_ADDRESS
    assert TRANSFER_IAT_MINT == IAT_TOKEN_ADDRESS


def test_iat_mint_can_be_overridden_per_cluster():
    devnet_mint = "2ZT8Yh4kPYCJ8BQmx6uNPCAXVUHqQF8rd8h7cia5UeD7"
    env = {**os.environ, "IAT_TOKEN_ADDRESS": devnet_mint}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from iat.config import IAT_TOKEN_ADDRESS; print(IAT_TOKEN_ADDRESS)",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == devnet_mint


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
