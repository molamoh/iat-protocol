"""Wallet-signature authentication for IAT's permanent buyer inbox."""

from __future__ import annotations

import hashlib
import json
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS buyer_purchase_policies (
                wallet TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                input_asset TEXT NOT NULL,
                max_per_order_minor INTEGER NOT NULL,
                daily_limit_minor INTEGER NOT NULL,
                allowed_services TEXT NOT NULL DEFAULT '[]',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS buyer_spend_reservations (
                quote_id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                input_asset TEXT NOT NULL,
                amount_minor INTEGER NOT NULL,
                service TEXT,
                state TEXT NOT NULL DEFAULT 'reserved',
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_buyer_spend_wallet_day "
            "ON buyer_spend_reservations(wallet,input_asset,created_at,expires_at)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS buyer_intent_decisions (
                intent_decision_id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                request_json TEXT NOT NULL,
                selection_json TEXT NOT NULL,
                selected_seller_agent_id TEXT,
                selected_agent_id TEXT,
                selected_catalog_item_id TEXT,
                selected_unit_price TEXT,
                selected_currency TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER,
                order_id TEXT,
                UNIQUE(wallet,idempotency_key)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_buyer_intent_wallet_expires "
            "ON buyer_intent_decisions(wallet,expires_at,consumed_at)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def create_wallet_challenge(
    wallet: str,
    *,
    now: int | None = None,
    statement: str = "Sign in to access your IAT delivery inbox. This does not authorize a transaction or payment.",
) -> dict[str, Any]:
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
            f"Statement: {str(statement).strip()[:240]}",
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


def save_buyer_purchase_policy(
    wallet: str,
    *,
    enabled: bool,
    input_asset: str,
    max_per_order_minor: int,
    daily_limit_minor: int,
    allowed_services: list[str] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    wallet = validate_wallet(wallet)
    asset = str(input_asset or "").strip().upper()
    per_order = int(max_per_order_minor)
    daily = int(daily_limit_minor)
    if asset != "USDC":
        raise WalletIdentityError("unsupported_purchase_policy_asset")
    if per_order <= 0 or daily <= 0 or per_order > daily:
        raise WalletIdentityError("invalid_purchase_policy_limits")
    services = sorted({str(item).strip().lower() for item in (allowed_services or []) if str(item).strip()})
    if len(services) > 50 or any(len(item) > 100 for item in services):
        raise WalletIdentityError("invalid_purchase_policy_services")
    current = int(time.time()) if now is None else int(now)
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        if database.USE_POSTGRES:
            cur.execute(
                f"""INSERT INTO buyer_purchase_policies
                (wallet,enabled,input_asset,max_per_order_minor,daily_limit_minor,allowed_services,created_at,updated_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
                ON CONFLICT (wallet) DO UPDATE SET enabled=EXCLUDED.enabled,
                input_asset=EXCLUDED.input_asset,max_per_order_minor=EXCLUDED.max_per_order_minor,
                daily_limit_minor=EXCLUDED.daily_limit_minor,allowed_services=EXCLUDED.allowed_services,
                updated_at=EXCLUDED.updated_at""",
                (wallet, int(enabled), asset, per_order, daily, json.dumps(services), current, current),
            )
        else:
            cur.execute(
                f"""INSERT INTO buyer_purchase_policies
                (wallet,enabled,input_asset,max_per_order_minor,daily_limit_minor,allowed_services,created_at,updated_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
                ON CONFLICT(wallet) DO UPDATE SET enabled=excluded.enabled,
                input_asset=excluded.input_asset,max_per_order_minor=excluded.max_per_order_minor,
                daily_limit_minor=excluded.daily_limit_minor,allowed_services=excluded.allowed_services,
                updated_at=excluded.updated_at""",
                (wallet, int(enabled), asset, per_order, daily, json.dumps(services), current, current),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)
    return get_buyer_purchase_policy(wallet) or {}


def get_buyer_purchase_policy(wallet: str) -> dict[str, Any] | None:
    wallet = validate_wallet(wallet)
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM buyer_purchase_policies WHERE wallet={p}", (wallet,))
        row = cur.fetchone()
        if not row:
            return None
        policy = dict(row)
        policy["enabled"] = bool(policy.get("enabled"))
        try:
            policy["allowed_services"] = json.loads(policy.get("allowed_services") or "[]")
        except (TypeError, ValueError):
            policy["allowed_services"] = []
        return policy
    finally:
        release_conn(conn)


def authorize_buyer_spend(
    wallet: str,
    *,
    quote_id: str,
    input_asset: str,
    amount_minor: int,
    service: str = "",
    expires_at: int,
    now: int | None = None,
) -> dict[str, Any]:
    """Atomically reserve a bounded autonomous spend under the wallet policy."""
    wallet = validate_wallet(wallet)
    current = int(time.time()) if now is None else int(now)
    amount = int(amount_minor)
    asset = str(input_asset or "").strip().upper()
    normalized_service = str(service or "").strip().lower()
    if amount <= 0 or int(expires_at) <= current:
        raise WalletIdentityError("invalid_autonomous_spend")
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        lock = " FOR UPDATE" if database.USE_POSTGRES else ""
        cur.execute(f"SELECT * FROM buyer_purchase_policies WHERE wallet={p}{lock}", (wallet,))
        row = cur.fetchone()
        if not row or not bool(dict(row).get("enabled")):
            raise WalletIdentityError("autonomous_purchase_policy_required")
        policy = dict(row)
        if asset != str(policy.get("input_asset") or "").upper():
            raise WalletIdentityError("purchase_policy_asset_blocked")
        if amount > int(policy.get("max_per_order_minor") or 0):
            raise WalletIdentityError("purchase_policy_order_limit_exceeded")
        allowed = json.loads(policy.get("allowed_services") or "[]")
        if allowed and normalized_service not in allowed:
            raise WalletIdentityError("purchase_policy_service_blocked")
        cur.execute(f"SELECT * FROM buyer_spend_reservations WHERE quote_id={p}", (quote_id,))
        existing = cur.fetchone()
        if existing:
            reservation = dict(existing)
            if reservation.get("wallet") != wallet or int(reservation.get("amount_minor") or 0) != amount:
                raise WalletIdentityError("autonomous_spend_idempotency_conflict")
            conn.commit()
            return {"status": "already_reserved", **reservation}
        day_start = current - (current % 86400)
        cur.execute(
            f"""SELECT COALESCE(SUM(amount_minor),0) AS total FROM buyer_spend_reservations
            WHERE wallet={p} AND input_asset={p} AND created_at>={p} AND expires_at>{p}
            AND state IN ('reserved','submitted','confirmed')""",
            (wallet, asset, day_start, current),
        )
        reserved = int(dict(cur.fetchone()).get("total") or 0)
        if reserved + amount > int(policy.get("daily_limit_minor") or 0):
            raise WalletIdentityError("purchase_policy_daily_limit_exceeded")
        cur.execute(
            f"""INSERT INTO buyer_spend_reservations
            (quote_id,wallet,input_asset,amount_minor,service,state,created_at,expires_at)
            VALUES ({p},{p},{p},{p},{p},'reserved',{p},{p})""",
            (quote_id, wallet, asset, amount, normalized_service, current, int(expires_at)),
        )
        conn.commit()
        return {
            "status": "reserved",
            "quote_id": quote_id,
            "amount_minor": amount,
            "input_asset": asset,
            "daily_reserved_minor": reserved + amount,
            "daily_limit_minor": int(policy["daily_limit_minor"]),
            "expires_at": int(expires_at),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def update_buyer_spend_reservation(
    quote_id: str,
    state: str,
    *,
    now: int | None = None,
) -> bool:
    normalized_state = str(state or "").strip().lower()
    if normalized_state not in {"submitted", "confirmed", "released"}:
        raise WalletIdentityError("invalid_spend_reservation_state")
    current = int(time.time()) if now is None else int(now)
    # Submitted and confirmed funds remain part of today's consumed budget.
    effective_expiry = (
        current - (current % 86400) + 86400
        if normalized_state in {"submitted", "confirmed"}
        else current
    )
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"UPDATE buyer_spend_reservations SET state={p},expires_at={p} WHERE quote_id={p}",
            (normalized_state, effective_expiry, str(quote_id)),
        )
        changed = cur.rowcount == 1
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def save_buyer_intent_decision(
    wallet: str,
    *,
    idempotency_key: str,
    request_payload: dict[str, Any],
    selection: dict[str, Any],
    selected_record: dict[str, Any] | None,
    now: int | None = None,
    ttl_seconds: int = 120,
) -> dict[str, Any]:
    wallet = validate_wallet(wallet)
    key = str(idempotency_key or "").strip()
    if not 8 <= len(key) <= 128:
        raise WalletIdentityError("invalid_intent_idempotency_key")
    current = int(time.time()) if now is None else int(now)
    ttl = max(30, min(int(ttl_seconds), 300))
    canonical_request = json.dumps(request_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    request_hash = hashlib.sha256(canonical_request.encode()).hexdigest()
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM buyer_intent_decisions WHERE wallet={p} AND idempotency_key={p}",
            (wallet, key),
        )
        existing = cur.fetchone()
        if existing:
            row = dict(existing)
            if row.get("request_hash") != request_hash:
                raise WalletIdentityError("intent_idempotency_conflict")
            row["selection"] = json.loads(row.pop("selection_json"))
            row.pop("request_json", None)
            row["idempotent_replay"] = True
            conn.commit()
            return row
        decision_id = f"bid_{secrets.token_urlsafe(24)}"
        expires_at = current + ttl
        selected = selected_record or {}
        cur.execute(
            f"""INSERT INTO buyer_intent_decisions
            (intent_decision_id,wallet,idempotency_key,request_hash,request_json,selection_json,
             selected_seller_agent_id,selected_agent_id,selected_catalog_item_id,
             selected_unit_price,selected_currency,created_at,expires_at,consumed_at,order_id)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},NULL,NULL)""",
            (
                decision_id, wallet, key, request_hash, canonical_request,
                json.dumps(selection, sort_keys=True),
                selected.get("seller_agent_id"), selected.get("agent_id"),
                selected.get("catalog_item_id"), str(selected.get("unit_price")) if selected else None,
                selected.get("currency"), current, expires_at,
            ),
        )
        conn.commit()
        return {
            "intent_decision_id": decision_id,
            "wallet": wallet,
            "idempotency_key": key,
            "request_hash": request_hash,
            "selection": selection,
            "selected_seller_agent_id": selected.get("seller_agent_id"),
            "selected_agent_id": selected.get("agent_id"),
            "selected_catalog_item_id": selected.get("catalog_item_id"),
            "selected_unit_price": str(selected.get("unit_price")) if selected else None,
            "selected_currency": selected.get("currency"),
            "created_at": current,
            "expires_at": expires_at,
            "consumed_at": None,
            "order_id": None,
            "idempotent_replay": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def get_buyer_intent_decision(
    wallet: str,
    intent_decision_id: str,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    """Read a wallet-bound decision without claiming or mutating it."""
    wallet = validate_wallet(wallet)
    current = int(time.time()) if now is None else int(now)
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM buyer_intent_decisions WHERE intent_decision_id={p} AND wallet={p}",
            (str(intent_decision_id), wallet),
        )
        row = cur.fetchone()
        if not row:
            raise WalletIdentityError("intent_decision_not_found")
        decision = dict(row)
        if not decision.get("order_id") and current >= int(decision["expires_at"]):
            raise WalletIdentityError("intent_decision_expired")
        decision["request"] = json.loads(decision.pop("request_json"))
        decision["selection"] = json.loads(decision.pop("selection_json"))
        return decision
    finally:
        release_conn(conn)


def claim_buyer_intent_decision(
    wallet: str,
    intent_decision_id: str,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    wallet = validate_wallet(wallet)
    current = int(time.time()) if now is None else int(now)
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        lock = " FOR UPDATE" if database.USE_POSTGRES else ""
        cur.execute(
            f"SELECT * FROM buyer_intent_decisions WHERE intent_decision_id={p} AND wallet={p}{lock}",
            (str(intent_decision_id), wallet),
        )
        row = cur.fetchone()
        if not row:
            raise WalletIdentityError("intent_decision_not_found")
        decision = dict(row)
        if decision.get("order_id"):
            decision["request"] = json.loads(decision.pop("request_json"))
            decision["selection"] = json.loads(decision.pop("selection_json"))
            decision["idempotent_replay"] = True
            conn.commit()
            return decision
        if current >= int(decision["expires_at"]):
            raise WalletIdentityError("intent_decision_expired")
        claimed_at = decision.get("consumed_at")
        if claimed_at is not None and int(claimed_at) > current - 30:
            raise WalletIdentityError("intent_decision_commit_in_progress")
        cur.execute(
            f"""UPDATE buyer_intent_decisions SET consumed_at={p}
            WHERE intent_decision_id={p} AND wallet={p} AND order_id IS NULL
            AND (consumed_at IS NULL OR consumed_at<={p})""",
            (current, str(intent_decision_id), wallet, current - 30),
        )
        if cur.rowcount != 1:
            raise WalletIdentityError("intent_decision_commit_in_progress")
        conn.commit()
        decision["consumed_at"] = current
        decision["request"] = json.loads(decision.pop("request_json"))
        decision["selection"] = json.loads(decision.pop("selection_json"))
        decision["idempotent_replay"] = False
        return decision
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def finalize_buyer_intent_decision(wallet: str, intent_decision_id: str, order_id: str) -> bool:
    wallet = validate_wallet(wallet)
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE buyer_intent_decisions SET order_id={p}
            WHERE intent_decision_id={p} AND wallet={p} AND consumed_at IS NOT NULL
            AND order_id IS NULL""",
            (str(order_id), str(intent_decision_id), wallet),
        )
        changed = cur.rowcount == 1
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def release_buyer_intent_decision_claim(wallet: str, intent_decision_id: str) -> bool:
    wallet = validate_wallet(wallet)
    init_wallet_identity_db()
    conn = get_conn()
    try:
        p = qmark()
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE buyer_intent_decisions SET consumed_at=NULL
            WHERE intent_decision_id={p} AND wallet={p} AND order_id IS NULL""",
            (str(intent_decision_id), wallet),
        )
        changed = cur.rowcount == 1
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)
