"""Wallet-signature authentication for IAT's permanent buyer inbox."""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from typing import Any

from solders.pubkey import Pubkey
from solders.signature import Signature

from iat.api import db as database
from iat.api.db import get_conn, qmark, release_conn


class WalletIdentityError(ValueError):
    pass


def _bounded_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _challenge_ttl() -> int:
    return _bounded_env("IAT_WALLET_CHALLENGE_TTL_SECONDS", 300, 60, 600)


def _session_ttl() -> int:
    return _bounded_env("IAT_WALLET_SESSION_TTL_SECONDS", 1800, 300, 86400)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_wallet(wallet: str) -> str:
    value = str(wallet or "").strip()
    try:
        parsed = Pubkey.from_string(value)
    except Exception as exc:
        raise WalletIdentityError("invalid_wallet") from exc
    if str(parsed) != value:
        raise WalletIdentityError("invalid_wallet")
    return value


def init_wallet_identity_db() -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_auth_challenges (
                challenge_id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                used_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_auth_sessions (
                token_hash TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                last_used_at INTEGER NOT NULL,
                revoked_at INTEGER
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_auth_challenges_wallet_created "
            "ON wallet_auth_challenges(wallet, created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_auth_sessions_wallet_expires "
            "ON wallet_auth_sessions(wallet, expires_at)"
        )
        conn.commit()
    finally:
        release_conn(conn)


def create_wallet_challenge(wallet: str, *, now: int | None = None) -> dict[str, Any]:
    wallet = validate_wallet(wallet)
    issued_at = int(time.time()) if now is None else int(now)
    expires_at = issued_at + _challenge_ttl()
    challenge_id = f"iwc_{secrets.token_urlsafe(24)}"
    nonce = secrets.token_urlsafe(32)
    message = "\n".join(
        (
            "IAT Protocol Wallet Authentication",
            "Domain: iatprotocol.com",
            "URI: https://iatprotocol.com",
            "Version: 1",
            "Cluster: devnet",
            f"Wallet: {wallet}",
            f"Challenge: {nonce}",
            f"Issued At: {issued_at}",
            f"Expires At: {expires_at}",
            "Statement: Sign in to access your IAT delivery inbox. This does not authorize a transaction or payment.",
        )
    )
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"SELECT COUNT(*) AS count FROM wallet_auth_challenges "
            f"WHERE wallet={p} AND created_at>={p}",
            (wallet, issued_at - 60),
        )
        count = int(dict(cur.fetchone()).get("count", 0))
        if count >= 5:
            raise WalletIdentityError("wallet_challenge_rate_limited")
        cur.execute(
            f"INSERT INTO wallet_auth_challenges "
            f"(challenge_id,wallet,message,created_at,expires_at,used_at) "
            f"VALUES ({p},{p},{p},{p},{p},NULL)",
            (challenge_id, wallet, message, issued_at, expires_at),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)
    return {
        "challenge_id": challenge_id,
        "wallet": wallet,
        "message": message,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "signing_notice": "Authentication only. No transaction or payment is authorized.",
    }


def exchange_wallet_signature(
    challenge_id: str,
    signature: str,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    current = int(time.time()) if now is None else int(now)
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM wallet_auth_challenges WHERE challenge_id={p}",
            (str(challenge_id),),
        )
        row = cur.fetchone()
        if not row:
            raise WalletIdentityError("invalid_wallet_challenge")
        challenge = dict(row)
        if challenge.get("used_at") is not None or current >= int(challenge["expires_at"]):
            raise WalletIdentityError("invalid_wallet_challenge")
        try:
            verified = Signature.from_string(str(signature)).verify(
                Pubkey.from_string(str(challenge["wallet"])),
                str(challenge["message"]).encode("utf-8"),
            )
        except Exception:
            verified = False
        if not verified:
            raise WalletIdentityError("invalid_wallet_signature")

        cur.execute(
            f"UPDATE wallet_auth_challenges SET used_at={p} "
            f"WHERE challenge_id={p} AND used_at IS NULL AND expires_at>{p}",
            (current, challenge_id, current),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise WalletIdentityError("invalid_wallet_challenge")
        token = f"ias_{secrets.token_urlsafe(32)}"
        expires_at = current + _session_ttl()
        cur.execute(
            f"INSERT INTO wallet_auth_sessions "
            f"(token_hash,wallet,created_at,expires_at,last_used_at,revoked_at) "
            f"VALUES ({p},{p},{p},{p},{p},NULL)",
            (_token_hash(token), challenge["wallet"], current, expires_at, current),
        )
        conn.commit()
        return {
            "access_token": token,
            "token_type": "Bearer",
            "wallet": challenge["wallet"],
            "expires_at": expires_at,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def authenticate_wallet_session(token: str, *, now: int | None = None) -> str:
    value = str(token or "")
    if not value.startswith("ias_") or len(value) > 128:
        raise WalletIdentityError("invalid_wallet_session")
    current = int(time.time()) if now is None else int(now)
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        digest = _token_hash(value)
        cur.execute(
            f"SELECT wallet FROM wallet_auth_sessions WHERE token_hash={p} "
            f"AND revoked_at IS NULL AND expires_at>{p}",
            (digest, current),
        )
        row = cur.fetchone()
        if not row:
            raise WalletIdentityError("invalid_wallet_session")
        wallet = str(dict(row)["wallet"])
        cur.execute(
            f"UPDATE wallet_auth_sessions SET last_used_at={p} WHERE token_hash={p}",
            (current, digest),
        )
        conn.commit()
        return wallet
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def revoke_wallet_session(token: str, *, now: int | None = None) -> bool:
    value = str(token or "")
    if not value.startswith("ias_") or len(value) > 128:
        return False
    current = int(time.time()) if now is None else int(now)
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"UPDATE wallet_auth_sessions SET revoked_at={p} "
            f"WHERE token_hash={p} AND revoked_at IS NULL",
            (current, _token_hash(value)),
        )
        changed = cur.rowcount == 1
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)
