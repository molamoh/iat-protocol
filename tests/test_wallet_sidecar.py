import base64
import asyncio
import time

import httpx
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from iat.wallet_sidecar import create_wallet_sidecar_app


KEYPAIR = Keypair.from_seed(bytes([10]) * 32)
WALLET = str(KEYPAIR.pubkey())
TOKEN = "sidecar-test-token-long-enough"


class Backend:
    wallet_address = WALLET

    def __init__(self):
        self.calls = []

    def approve_sign_and_broadcast(self, transaction_base64, review):
        self.calls.append((transaction_base64, dict(review)))
        return str(Signature.default())


def transaction(fee_payer=KEYPAIR.pubkey()):
    message = Message.new_with_blockhash([], fee_payer, Hash.default())
    value = VersionedTransaction.populate(message, [Signature.default()])
    return base64.b64encode(bytes(value)).decode()


def request_payload(**overrides):
    payload = {
        "operation": "sign_and_broadcast_solana_transaction",
        "wallet_address": WALLET,
        "transaction_base64": transaction(),
        "review": {
            "cluster": "solana:devnet",
            "fee_payer": WALLET,
            "expires_at": int(time.time()) + 120,
            "simulation": {"status": "succeeded", "units_consumed": 1000},
            "input": {"asset": "USDC", "amount_minor": 1_000_000},
        },
    }
    payload.update(overrides)
    return payload


def client():
    backend = Backend()
    app = create_wallet_sidecar_app(backend, auth_token=TOKEN)
    return app, backend


def call(app, method, path, **kwargs):
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as api:
            return await api.request(method, path, **kwargs)

    return asyncio.run(request())


def test_sidecar_validates_and_delegates_without_key_material():
    api, backend = client()
    response = call(
        api,
        "POST",
        "/v1/wallet/sign-and-broadcast",
        json=request_payload(),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json()["wallet_address"] == WALLET
    assert len(backend.calls) == 1
    assert "private" not in str(backend.calls[0]).lower()


def test_sidecar_replay_is_idempotent_and_never_signs_twice():
    api, backend = client()
    payload = request_payload()
    first = call(
        api,
        "POST",
        "/v1/wallet/sign-and-broadcast",
        json=payload,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    second = call(
        api,
        "POST",
        "/v1/wallet/sign-and-broadcast",
        json=payload,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert first.json()["idempotent"] is False
    assert second.json()["idempotent"] is True
    assert len(backend.calls) == 1


def test_sidecar_requires_its_own_token():
    api, backend = client()
    response = call(api, "POST", "/v1/wallet/sign-and-broadcast", json=request_payload())
    assert response.status_code == 401
    assert backend.calls == []


def test_sidecar_fails_closed_before_backend_for_unsafe_requests():
    cases = [
        (request_payload(wallet_address=str(Keypair().pubkey())), 409),
        (request_payload(review={"cluster": "solana:mainnet", "fee_payer": WALLET}), 403),
        (
            request_payload(
                review={
                    "cluster": "solana:devnet",
                    "fee_payer": WALLET,
                    "expires_at": int(time.time()) + 120,
                    "simulation": {"status": "failed"},
                }
            ),
            409,
        ),
        (request_payload(transaction_base64="x" * 64), 422),
        (
            request_payload(
                transaction_base64=transaction(Keypair.from_seed(bytes([11]) * 32).pubkey())
            ),
            409,
        ),
    ]
    for payload, status in cases:
        api, backend = client()
        response = call(
            api,
            "POST",
            "/v1/wallet/sign-and-broadcast",
            json=payload,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == status
        assert backend.calls == []


def test_sidecar_health_discloses_only_public_configuration():
    api, _ = client()
    body = call(api, "GET", "/health").json()
    assert body == {
        "status": "ready",
        "wallet_address": WALLET,
        "allowed_clusters": ["solana:devnet"],
        "key_custody": "external_backend",
    }
    assert TOKEN not in str(body)
