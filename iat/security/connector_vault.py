"""Authenticated encryption for hosted seller connector credentials."""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _vault_key() -> bytes:
    master = os.getenv("IAT_CONNECTOR_VAULT_KEY") or os.getenv("IAT_ADMIN_API_KEY")
    if not master or len(master) < 24:
        raise RuntimeError("connector_vault_key_unavailable")
    return hashlib.sha256(
        b"iat-managed-connector-v1\x00" + master.encode("utf-8")
    ).digest()


def encrypt_connector_secret(seller_id: str, secret: str | None) -> str | None:
    if not secret:
        return None
    nonce = os.urandom(12)
    ciphertext = AESGCM(_vault_key()).encrypt(
        nonce,
        secret.encode("utf-8"),
        str(seller_id).encode("utf-8"),
    )
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_connector_secret(seller_id: str, encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    payload = base64.urlsafe_b64decode(encrypted.encode("ascii"))
    if len(payload) < 29:
        raise ValueError("connector_secret_ciphertext_invalid")
    plaintext = AESGCM(_vault_key()).decrypt(
        payload[:12],
        payload[12:],
        str(seller_id).encode("utf-8"),
    )
    return plaintext.decode("utf-8")
