import base64

from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from iat import settlement_sidecar


def test_local_settlement_sidecar_is_not_configured_without_render_secrets(monkeypatch):
    for name in (
        "IAT_ESCROW_KEYPAIR_JSON",
        "IAT_ESCROW_KEYPAIR_PATH",
        "IAT_ESCROW_WALLET",
        "IAT_PROTOCOL_TREASURY_WALLET",
        "IAT_SETTLEMENT_WALLET_SIDECAR_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    assert settlement_sidecar.create_settlement_sidecar_app_from_env() is None
    diagnostic = settlement_sidecar.settlement_sidecar_diagnostic()
    assert diagnostic["local_only"] is True
    assert diagnostic["status"] == "settlement_sidecar_not_ready"
    assert "IAT_SETTLEMENT_WALLET_SIDECAR_TOKEN" in diagnostic["missing_checks"]


def test_local_escrow_signer_signs_only_required_empty_slot():
    keypair = Keypair.from_seed(bytes([31]) * 32)
    message = Message.new_with_blockhash([], keypair.pubkey(), Hash.default())
    unsigned = VersionedTransaction.populate(message, [Signature.default()])
    signer = settlement_sidecar.LocalEscrowDetachedSigner(keypair)
    encoded = signer.sign_transaction(base64.b64encode(bytes(unsigned)).decode(), {})
    signed = VersionedTransaction.from_bytes(base64.b64decode(encoded))
    assert signed.signatures[0] != Signature.default()
    assert signed.signatures[0].verify(keypair.pubkey(), bytes(signed.message))


def test_local_settlement_sidecar_assembles_from_existing_escrow_keypair(tmp_path, monkeypatch):
    keypair = Keypair.from_seed(bytes([32]) * 32)
    keypath = tmp_path / "escrow.json"
    keypath.write_text(str(list(bytes(keypair))), encoding="utf-8")
    monkeypatch.setenv("IAT_ESCROW_KEYPAIR_PATH", str(keypath))
    monkeypatch.setenv("IAT_ESCROW_WALLET", str(keypair.pubkey()))
    monkeypatch.setenv("IAT_PROTOCOL_TREASURY_WALLET", str(Keypair().pubkey()))
    monkeypatch.setenv("IAT_SETTLEMENT_WALLET_SIDECAR_TOKEN", "sidecar-token-long-enough")
    app = settlement_sidecar.create_settlement_sidecar_app_from_env()
    assert app is not None
    assert any(route.path == "/health" for route in app.routes)
    assert settlement_sidecar.settlement_sidecar_diagnostic()["status"] == "settlement_sidecar_ready"
