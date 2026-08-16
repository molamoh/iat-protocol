import pytest
from solders.keypair import Keypair
from solders.signature import Signature

from iat.wallet_adapters import LocalWalletRPCAdapter, WalletAdapterError


WALLET = str(Keypair.from_seed(bytes([9]) * 32).pubkey())
TOKEN = "local-wallet-token-long-enough"


class Response:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def adapter(response=None):
    return LocalWalletRPCAdapter(
        "http://127.0.0.1:8787",
        wallet_address=WALLET,
        auth_token=TOKEN,
        session=Session(
            response
            or Response(
                {
                    "approved": True,
                    "wallet_address": WALLET,
                    "tx_signature": str(Signature.default()),
                }
            )
        ),
    )


def test_local_wallet_adapter_sends_only_public_transaction_contract():
    wallet = adapter()
    signature = wallet.sign_and_broadcast(
        "transaction-base64",
        {"cluster": "solana:devnet", "fee_payer": WALLET, "input": {"asset": "USDC"}},
    )
    assert signature == str(Signature.default())
    url, request = wallet.session.calls[0]
    assert url == "http://127.0.0.1:8787/v1/wallet/sign-and-broadcast"
    assert request["allow_redirects"] is False
    assert request["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request["json"])
    assert "private" not in str(request["json"]).lower()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://wallet.example",
        "https://wallet.example",
        "http://localhost:8787",
        "ftp://127.0.0.1:8787",
        "http://token@127.0.0.1:8787",
    ],
)
def test_wallet_adapter_rejects_unsafe_endpoint_by_default(endpoint):
    with pytest.raises(ValueError):
        LocalWalletRPCAdapter(
            endpoint,
            wallet_address=WALLET,
            auth_token=TOKEN,
        )


def test_remote_wallet_requires_explicit_https_opt_in():
    wallet = LocalWalletRPCAdapter(
        "https://wallet.example",
        wallet_address=WALLET,
        auth_token=TOKEN,
        allow_remote_https=True,
    )
    assert wallet.wallet_address == WALLET


def test_wallet_adapter_rejects_review_for_another_fee_payer():
    wallet = adapter()
    with pytest.raises(WalletAdapterError, match="wallet_review_fee_payer_mismatch"):
        wallet.sign_and_broadcast(
            "transaction-base64",
            {"cluster": "solana:devnet", "fee_payer": str(Keypair().pubkey())},
        )
    assert wallet.session.calls == []


@pytest.mark.parametrize(
    "response,code",
    [
        (Response({}, 302), "wallet_sidecar_redirect_rejected"),
        (Response({"approved": False}), "wallet_sidecar_did_not_approve"),
        (
            Response(
                {
                    "approved": True,
                    "wallet_address": str(Keypair().pubkey()),
                    "tx_signature": str(Signature.default()),
                }
            ),
            "wallet_sidecar_identity_mismatch",
        ),
        (
            Response({"approved": True, "wallet_address": WALLET, "tx_signature": "invalid"}),
            "wallet_sidecar_signature_invalid",
        ),
    ],
)
def test_wallet_adapter_fails_closed_on_untrusted_sidecar_response(response, code):
    wallet = adapter(response)
    with pytest.raises(WalletAdapterError, match=code):
        wallet.sign_and_broadcast(
            "transaction-base64", {"cluster": "solana:devnet", "fee_payer": WALLET}
        )
