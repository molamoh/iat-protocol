import hashlib
import sqlite3

import pytest
from solders.keypair import Keypair

from iat.api import db
from iat import buyer_identity


@pytest.fixture()
def identity_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "identity.sqlite")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    monkeypatch.setenv("IAT_WALLET_CHALLENGE_TTL_SECONDS", "300")
    monkeypatch.setenv("IAT_WALLET_SESSION_TTL_SECONDS", "1800")


def _signed_session(keypair: Keypair, *, now: int = 1_000):
    challenge = buyer_identity.create_wallet_challenge(str(keypair.pubkey()), now=now)
    signature = keypair.sign_message(challenge["message"].encode("utf-8"))
    session = buyer_identity.exchange_wallet_signature(
        challenge["challenge_id"], str(signature), now=now + 1
    )
    return challenge, session


def test_valid_signature_creates_hashed_short_lived_session(identity_db):
    keypair = Keypair()
    challenge, session = _signed_session(keypair)

    assert challenge["message"].startswith("IAT Protocol Wallet Authentication\n")
    assert "does not authorize a transaction or payment" in challenge["message"]
    assert session["wallet"] == str(keypair.pubkey())
    assert buyer_identity.authenticate_wallet_session(
        session["access_token"], now=1_002
    ) == str(keypair.pubkey())

    conn = sqlite3.connect(db.DB_PATH)
    stored = conn.execute(
        "SELECT token_hash FROM wallet_auth_sessions"
    ).fetchone()[0]
    conn.close()
    assert stored == hashlib.sha256(session["access_token"].encode()).hexdigest()
    assert stored != session["access_token"]


def test_wrong_signature_and_challenge_replay_are_rejected(identity_db):
    owner = Keypair()
    attacker = Keypair()
    challenge = buyer_identity.create_wallet_challenge(str(owner.pubkey()), now=1_000)

    with pytest.raises(buyer_identity.WalletIdentityError, match="invalid_wallet_signature"):
        buyer_identity.exchange_wallet_signature(
            challenge["challenge_id"],
            str(attacker.sign_message(challenge["message"].encode())),
            now=1_001,
        )

    valid = str(owner.sign_message(challenge["message"].encode()))
    buyer_identity.exchange_wallet_signature(challenge["challenge_id"], valid, now=1_002)
    with pytest.raises(buyer_identity.WalletIdentityError, match="invalid_wallet_challenge"):
        buyer_identity.exchange_wallet_signature(challenge["challenge_id"], valid, now=1_003)


def test_expired_challenge_and_revoked_or_expired_session_are_rejected(identity_db):
    keypair = Keypair()
    challenge = buyer_identity.create_wallet_challenge(str(keypair.pubkey()), now=1_000)
    signature = str(keypair.sign_message(challenge["message"].encode()))
    with pytest.raises(buyer_identity.WalletIdentityError, match="invalid_wallet_challenge"):
        buyer_identity.exchange_wallet_signature(
            challenge["challenge_id"], signature, now=challenge["expires_at"]
        )

    _, session = _signed_session(keypair, now=2_000)
    assert buyer_identity.revoke_wallet_session(session["access_token"], now=2_010)
    with pytest.raises(buyer_identity.WalletIdentityError, match="invalid_wallet_session"):
        buyer_identity.authenticate_wallet_session(session["access_token"], now=2_011)

    _, expiring = _signed_session(Keypair(), now=3_000)
    with pytest.raises(buyer_identity.WalletIdentityError, match="invalid_wallet_session"):
        buyer_identity.authenticate_wallet_session(
            expiring["access_token"], now=expiring["expires_at"]
        )


def test_invalid_wallet_and_challenge_flood_are_rejected(identity_db):
    with pytest.raises(buyer_identity.WalletIdentityError, match="invalid_wallet"):
        buyer_identity.create_wallet_challenge("not-a-solana-wallet", now=1_000)

    wallet = str(Keypair().pubkey())
    for second in range(5):
        buyer_identity.create_wallet_challenge(wallet, now=1_000 + second)
    with pytest.raises(buyer_identity.WalletIdentityError, match="rate_limited"):
        buyer_identity.create_wallet_challenge(wallet, now=1_010)
