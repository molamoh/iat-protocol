"""Opted-in staging agent used to validate IAT acquisition end to end."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field


ALLOWED_MODES = {
    "interested",
    "not_interested",
    "needs_info",
    "integrated",
    "opt_out",
}
DB_PATH = Path(os.getenv("IAT_TEST_AGENT_DB_PATH", "/tmp/iat_growth_test_agent.db"))
_db_lock = threading.Lock()


class Invitation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: str = Field(pattern=r"^iat_protocol_invitation$")
    schema_version: str = Field(min_length=8, max_length=40)
    action_id: str = Field(min_length=10, max_length=100)
    prospect_id: str = Field(min_length=10, max_length=100)
    variant_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=2_000)
    discovery_url: str = Field(min_length=8, max_length=2_000)
    sandbox_url: str = Field(min_length=8, max_length=2_000)
    response_url: str = Field(min_length=8, max_length=2_000)
    response_token: str = Field(min_length=32, max_length=256)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_test_agent_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS invitations (
                    invitation_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    prospect_id TEXT NOT NULL,
                    variant_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    response_url TEXT NOT NULL,
                    response_token_hash TEXT NOT NULL,
                    response_type TEXT NOT NULL,
                    delivery_status TEXT NOT NULL,
                    callback_attempts INTEGER NOT NULL DEFAULT 0,
                    callback_status_code INTEGER,
                    callback_excerpt TEXT,
                    received_at INTEGER NOT NULL,
                    responded_at INTEGER,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def _mode() -> str:
    configured = os.getenv("IAT_TEST_AGENT_RESPONSE_MODE", "interested").strip().lower()
    return configured if configured in ALLOWED_MODES else "interested"


def _validate_response_url(url: str) -> None:
    allowed_base = os.getenv("IAT_TEST_AGENT_ALLOWED_IAT_BASE", "").strip().rstrip("/")
    if not allowed_base:
        raise HTTPException(status_code=503, detail="allowed_iat_base_not_configured")
    parsed = urlparse(url)
    allowed = urlparse(allowed_base)
    if (
        parsed.scheme != "https"
        or parsed.scheme != allowed.scheme
        or parsed.netloc.lower() != allowed.netloc.lower()
        or parsed.path != "/growth/v1/respond"
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=422, detail="response_url_not_allowed")


def _hourly_capacity_available() -> bool:
    maximum = max(1, min(int(os.getenv("IAT_TEST_AGENT_HOURLY_LIMIT", "100")), 1_000))
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM invitations WHERE received_at >= ?",
            (int(time.time()) - 3_600,),
        ).fetchone()
        return int(row["total"]) < maximum
    finally:
        conn.close()


def _store_invitation(invitation: Invitation, idempotency_key: str) -> tuple[str, bool]:
    now = int(time.time())
    invitation_id = f"tinv_{uuid.uuid4().hex}"
    token_hash = hashlib.sha256(invitation.response_token.encode()).hexdigest()
    with _db_lock:
        conn = _connect()
        try:
            existing = conn.execute(
                "SELECT * FROM invitations WHERE idempotency_key=? OR action_id=? LIMIT 1",
                (idempotency_key, invitation.action_id),
            ).fetchone()
            if existing:
                if (
                    existing["idempotency_key"] != idempotency_key
                    or existing["action_id"] != invitation.action_id
                ):
                    raise HTTPException(status_code=409, detail="invitation_idempotency_conflict")
                return existing["invitation_id"], False
            conn.execute(
                """INSERT INTO invitations
                (invitation_id, action_id, idempotency_key, prospect_id, variant_id,
                 message, response_url, response_token_hash, response_type,
                 delivery_status, received_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    invitation_id,
                    invitation.action_id,
                    idempotency_key,
                    invitation.prospect_id,
                    invitation.variant_id,
                    invitation.message,
                    invitation.response_url,
                    token_hash,
                    _mode(),
                    "received",
                    now,
                    now,
                ),
            )
            conn.commit()
            return invitation_id, True
        finally:
            conn.close()


def _record_callback(
    invitation_id: str,
    *,
    status: str,
    attempts: int,
    status_code: int | None,
    excerpt: str,
) -> None:
    now = int(time.time())
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                """UPDATE invitations SET delivery_status=?, callback_attempts=?,
                callback_status_code=?, callback_excerpt=?, responded_at=?,
                updated_at=? WHERE invitation_id=?""",
                (
                    status,
                    attempts,
                    status_code,
                    " ".join(str(excerpt).split())[:200],
                    now if status == "responded" else None,
                    now,
                    invitation_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def _respond_to_iat(invitation_id: str, invitation: Invitation) -> None:
    response_type = _mode()
    callback_payload = {
        "action_id": invitation.action_id,
        "response_token": invitation.response_token,
        "idempotency_key": f"test-agent-{invitation.action_id}",
        "response_type": response_type,
        "message": {
            "interested": "The staging agent is interested in evaluating IAT.",
            "not_interested": "The staging agent is not interested in IAT.",
            "needs_info": "The staging agent requests the sandbox integration contract.",
            "integrated": "The staging agent reports a completed test integration.",
            "opt_out": "The staging agent opts out of future invitations.",
        }[response_type],
        "metadata": {
            "agent": "iat-growth-test-agent",
            "environment": "staging",
            "variant_id": invitation.variant_id,
        },
    }
    attempts = 0
    status_code = None
    excerpt = ""
    for delay in (0, 1, 2):
        if delay:
            time.sleep(delay)
        attempts += 1
        try:
            response = requests.post(
                invitation.response_url,
                json=callback_payload,
                headers={
                    "User-Agent": "IAT-Growth-Test-Agent/1.0",
                    "Idempotency-Key": callback_payload["idempotency_key"],
                },
                timeout=(3.05, 10),
                allow_redirects=False,
            )
            status_code = response.status_code
            excerpt = response.text
            if 200 <= response.status_code < 300:
                _record_callback(
                    invitation_id,
                    status="responded",
                    attempts=attempts,
                    status_code=status_code,
                    excerpt=excerpt,
                )
                return
            if response.status_code < 500:
                break
        except requests.RequestException as exc:
            excerpt = f"{type(exc).__name__}: {exc}"
    _record_callback(
        invitation_id,
        status="callback_failed",
        attempts=attempts,
        status_code=status_code,
        excerpt=excerpt,
    )


def require_test_agent_admin(
    x_api_key: str | None = Header(default=None),
) -> bool:
    expected = os.getenv("IAT_TEST_AGENT_ADMIN_KEY")
    if not expected or not x_api_key or not secrets.compare_digest(expected, x_api_key):
        raise HTTPException(status_code=401, detail="unauthorized")
    return True


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_test_agent_db()
    yield


app = FastAPI(
    title="IAT Growth Test Agent",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "agent": "iat-growth-test-agent",
        "environment": "staging",
        "response_mode": _mode(),
        "callback_enabled": bool(os.getenv("IAT_TEST_AGENT_ALLOWED_IAT_BASE")),
    }


@app.post("/iat-invite", status_code=202)
def receive_invitation(
    invitation: Invitation,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key or not 8 <= len(idempotency_key) <= 160:
        raise HTTPException(status_code=422, detail="valid_idempotency_key_required")
    _validate_response_url(invitation.response_url)
    if not _hourly_capacity_available():
        raise HTTPException(status_code=429, detail="hourly_invitation_limit_reached")
    invitation_id, created = _store_invitation(invitation, idempotency_key)
    if created:
        background_tasks.add_task(_respond_to_iat, invitation_id, invitation)
    return {
        "status": "accepted" if created else "already_accepted",
        "invitation_id": invitation_id,
        "action_id": invitation.action_id,
        "response_scheduled": created,
    }


def _invitation_audit(limit: int):
    limit = max(1, min(int(limit), 500))
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT invitation_id, action_id, prospect_id, variant_id, message,
            response_type, delivery_status, callback_attempts, callback_status_code,
            callback_excerpt, received_at, responded_at, updated_at
            FROM invitations ORDER BY received_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return {
            "status": "ok",
            "count": len(rows),
            "invitations": [dict(row) for row in rows],
        }
    finally:
        conn.close()


@app.get("/admin/invitations")
@app.get("/audit/invitations")
def list_invitations(
    limit: int = 100,
    _admin: bool = Depends(require_test_agent_admin),
):
    return _invitation_audit(limit)
