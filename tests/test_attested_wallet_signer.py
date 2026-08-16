import base64

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from iat.attested_wallet_signer import (
    ATTESTATION_DOMAIN,
    AttestedHTTPSDetachedSigner,
    AttestedWalletSignerError,
)


KEYPAIR = Keypair.from_seed(bytes([13]) * 32)
WALLET = str(KEYPAIR.pubkey())
TOKEN = "agent-wallet-provider-token"


def unsigned_transaction():
    message = Message.new_with_blockhash([], KEYPAIR.pubkey(), Hash.default())
    tx = VersionedTransaction.populate(message, [Signature.default()])
    return base64.b64encode(bytes(tx)).decode()


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class ProviderSession:
    def __init__(self, *, wrong_attestation=False, wrong_binding=False):
        self.wrong_attestation = wrong_attestation
        self.wrong_binding = wrong_binding
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = kwargs["json"]
        if url.endswith("/v1/identity/attest"):
            message = base64.b64decode(payload["message_base64"])
            signature = (
                Keypair.from_seed(bytes([14]) * 32).sign_message(message)
                if self.wrong_attestation
                else KEYPAIR.sign_message(message)
            )
            return Response(
                {
                    "wallet_address": payload["wallet_address"],
                    "nonce": payload["nonce"],
                    "signature": str(signature),
                }
            )
        prepared = VersionedTransaction.from_bytes(
            base64.b64decode(payload["transaction_base64"])
        )
        signature = KEYPAIR.sign_message(bytes(prepared.message))
        signed = VersionedTransaction.populate(prepared.message, [signature])
        return Response(
            {
                "request_id": "wrong" if self.wrong_binding else payload["request_id"],
                "wallet_address": payload["wallet_address"],
                "transaction_sha256": payload["transaction_sha256"],
                "signed_transaction_base64": base64.b64encode(bytes(signed)).decode(),
            }
        )


def signer(session=None):
    return AttestedHTTPSDetachedSigner(
        "https://agent-wallet.example",
        wallet_address=WALLET,
        auth_token=TOKEN,
        session=session or ProviderSession(),
    )


def test_signer_attests_identity_then_returns_bound_signed_transaction():
    session = ProviderSession()
    value = signer(session)
    signed = value.sign_transaction(
        unsigned_transaction(),
        {"cluster": "solana:devnet", "fee_payer": WALLET},
    )
    assert VersionedTransaction.from_bytes(base64.b64decode(signed)).signatures[0] != Signature.default()
    assert len(session.calls) == 2
    attestation = session.calls[0][1]["json"]
    message = base64.b64decode(attestation["message_base64"])
    assert message.startswith(ATTESTATION_DOMAIN + b"\n")
    assert TOKEN not in str(attestation)
    assert session.calls[0][1]["allow_redirects"] is False


def test_attestation_is_cached_for_bounded_period():
    session = ProviderSession()
    value = signer(session)
    assert value.verify_identity()["cached"] is False
    assert value.verify_identity()["cached"] is True
    assert len(session.calls) == 1


def test_signer_rejects_invalid_wallet_attestation():
    session = ProviderSession(wrong_attestation=True)
    with pytest.raises(AttestedWalletSignerError, match="wallet_attestation_signature_invalid"):
        signer(session).sign_transaction(
            unsigned_transaction(), {"cluster": "solana:devnet", "fee_payer": WALLET}
        )
    assert len(session.calls) == 1


def test_signer_rejects_transaction_response_rebinding():
    session = ProviderSession(wrong_binding=True)
    with pytest.raises(AttestedWalletSignerError, match="signed_transaction_binding_mismatch"):
        signer(session).sign_transaction(
            unsigned_transaction(), {"cluster": "solana:devnet", "fee_payer": WALLET}
        )


def test_signer_rejects_insecure_remote_endpoint():
    with pytest.raises(ValueError, match="HTTPS"):
        AttestedHTTPSDetachedSigner(
            "http://agent-wallet.example",
            wallet_address=WALLET,
            auth_token=TOKEN,
        )
