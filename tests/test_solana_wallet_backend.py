import base64

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from iat.solana_wallet_backend import SolanaRPCWalletBackend, SolanaWalletBackendError


KEYPAIR = Keypair.from_seed(bytes([12]) * 32)
WALLET = str(KEYPAIR.pubkey())


def prepared_transaction(fee_payer=KEYPAIR.pubkey()):
    message = Message.new_with_blockhash([], fee_payer, Hash.default())
    tx = VersionedTransaction.populate(message, [Signature.default()])
    return base64.b64encode(bytes(tx)).decode()


class Signer:
    wallet_address = WALLET

    def __init__(self, *, change_message=False):
        self.change_message = change_message
        self.calls = []

    def sign_transaction(self, transaction_base64, review):
        self.calls.append((transaction_base64, dict(review)))
        prepared = VersionedTransaction.from_bytes(base64.b64decode(transaction_base64))
        message = (
            Message.new_with_blockhash([], KEYPAIR.pubkey(), Hash.from_bytes(bytes([1]) * 32))
            if self.change_message
            else prepared.message
        )
        signature = KEYPAIR.sign_message(bytes(message))
        signed = VersionedTransaction.populate(message, [signature])
        return base64.b64encode(bytes(signed)).decode()


class Approval:
    def __init__(self, approved=True):
        self.approved = approved
        self.calls = []

    def approve(self, review):
        self.calls.append(dict(review))
        return self.approved


class Response:
    def __init__(self, result, status_code=200):
        self.result = result
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http failure")

    def json(self):
        return self.result


class Session:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        signed = VersionedTransaction.from_bytes(
            base64.b64decode(kwargs["json"]["params"][0])
        )
        return Response({"jsonrpc": "2.0", "result": str(signed.signatures[0]), "id": 1})


def review():
    return {
        "cluster": "solana:devnet",
        "fee_payer": WALLET,
        "input": {"asset": "USDC", "amount_minor": 1_000_000},
        "simulation": {"status": "succeeded"},
    }


def backend(*, signer=None, approval=None, session=None):
    return SolanaRPCWalletBackend(
        signer=signer or Signer(),
        approval=approval or Approval(),
        session=session or Session(),
    )


def test_backend_approves_signs_verifies_and_broadcasts_with_preflight():
    signer = Signer()
    approval = Approval()
    session = Session()
    value = backend(signer=signer, approval=approval, session=session)
    signature = value.approve_sign_and_broadcast(prepared_transaction(), review())
    assert signature
    assert len(approval.calls) == len(signer.calls) == len(session.calls) == 1
    rpc = session.calls[0][1]["json"]
    assert rpc["method"] == "sendTransaction"
    assert rpc["params"][1] == {
        "encoding": "base64",
        "skipPreflight": False,
        "preflightCommitment": "confirmed",
        "maxRetries": 3,
    }
    assert session.calls[0][1]["allow_redirects"] is False


def test_backend_never_signs_or_broadcasts_without_approval():
    signer = Signer()
    session = Session()
    with pytest.raises(SolanaWalletBackendError, match="transaction_not_approved"):
        backend(signer=signer, approval=Approval(False), session=session).approve_sign_and_broadcast(
            prepared_transaction(), review()
        )
    assert signer.calls == []
    assert session.calls == []


def test_backend_rejects_signer_message_substitution_before_rpc():
    session = Session()
    with pytest.raises(SolanaWalletBackendError, match="signer_changed_transaction_message"):
        backend(signer=Signer(change_message=True), session=session).approve_sign_and_broadcast(
            prepared_transaction(), review()
        )
    assert session.calls == []


def test_backend_rejects_rpc_signature_substitution():
    class BadSession(Session):
        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response({"jsonrpc": "2.0", "result": str(Signature.default()), "id": 1})

    with pytest.raises(SolanaWalletBackendError, match="solana_rpc_signature_mismatch"):
        backend(session=BadSession()).approve_sign_and_broadcast(prepared_transaction(), review())


def test_backend_rejects_non_devnet_and_insecure_remote_rpc():
    with pytest.raises(ValueError, match="devnet"):
        SolanaRPCWalletBackend(
            signer=Signer(), approval=Approval(), cluster="solana:mainnet"
        )
    with pytest.raises(ValueError, match="HTTPS"):
        SolanaRPCWalletBackend(
            signer=Signer(), approval=Approval(), rpc_url="http://rpc.example"
        )
