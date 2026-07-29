"""Secure HTTP transport for GOIA partnership proposals.

This module is not wired into the dispatcher automatically.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import time
from typing import Any
from urllib.parse import urlparse

import requests
from pydantic import ValidationError
from solders.keypair import Keypair

from iat.goia.contracts import PartnershipAcknowledgement, PartnershipProposal
from iat.security.network import UnsafeNetworkTarget, validate_public_runtime_url


MAX_ACK_BYTES = 65_536
GOIA_PARTNERSHIP_USER_AGENT = "GOIA-Partnership/1.0"


class GOIAPartnershipTransportError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _signing_keypair() -> Keypair:
    encoded = os.getenv("IAT_GOIA_PARTNERSHIP_SIGNING_KEY", "").strip()
    if not encoded:
        raise GOIAPartnershipTransportError("partnership_signing_key_not_configured")
    try:
        return Keypair.from_base58_string(encoded)
    except ValueError as exc:
        raise GOIAPartnershipTransportError("invalid_partnership_signing_key") from exc


def signing_public_key() -> str:
    return str(_signing_keypair().pubkey())


def build_signed_request(
    proposal: dict[str, Any],
    *,
    now: int | None = None,
) -> tuple[bytes, dict[str, str]]:
    try:
        payload = PartnershipProposal.model_validate(proposal).model_dump(mode="json")
    except ValidationError as exc:
        raise GOIAPartnershipTransportError("invalid_partnership_proposal") from exc
    timestamp = int(now or time.time())
    body = _canonical_bytes(payload)
    content_hash = hashlib.sha256(body).hexdigest()
    signing_input = (
        f"{timestamp}\n{payload['proposal_id']}\n{content_hash}".encode()
    )
    keypair = _signing_keypair()
    signature = str(keypair.sign_message(signing_input))
    return body, {
        "Content-Type": "application/json",
        "User-Agent": GOIA_PARTNERSHIP_USER_AGENT,
        "Idempotency-Key": payload["proposal_id"],
        "X-GOIA-Key-Id": str(keypair.pubkey()),
        "X-GOIA-Timestamp": str(timestamp),
        "X-GOIA-Content-SHA256": content_hash,
        "X-GOIA-Signature": signature,
        "X-GOIA-Signature-Algorithm": "ed25519",
    }


def _connected_peer_ip(response: requests.Response) -> str:
    explicit = getattr(response, "peer_ip", None)
    if explicit:
        return str(explicit)
    try:
        return str(response.raw._connection.sock.getpeername()[0])
    except (AttributeError, IndexError, TypeError) as exc:
        raise GOIAPartnershipTransportError("connected_peer_unavailable") from exc


def _validate_connected_peer(response: requests.Response, target: dict[str, Any]) -> None:
    peer = _connected_peer_ip(response)
    try:
        address = ipaddress.ip_address(peer)
    except ValueError as exc:
        raise GOIAPartnershipTransportError("connected_peer_invalid") from exc
    if not address.is_global:
        raise GOIAPartnershipTransportError("connected_peer_must_be_public")
    if peer not in set(target["resolved_addresses"]):
        raise GOIAPartnershipTransportError("connected_peer_resolution_mismatch")


def _read_bounded(response: requests.Response) -> bytes:
    declared = response.headers.get("content-length")
    if declared:
        try:
            if int(declared) > MAX_ACK_BYTES:
                raise GOIAPartnershipTransportError("acknowledgement_too_large")
        except ValueError as exc:
            raise GOIAPartnershipTransportError("invalid_acknowledgement_length") from exc
    body = bytearray()
    for chunk in response.iter_content(chunk_size=8_192):
        body.extend(chunk)
        if len(body) > MAX_ACK_BYTES:
            raise GOIAPartnershipTransportError("acknowledgement_too_large")
    return bytes(body)


def _post_pinned_https(
    endpoint: str,
    *,
    target: dict[str, Any],
    body: bytes,
    headers: dict[str, str],
) -> tuple[int, dict[str, str], bytes]:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https":
        raise GOIAPartnershipTransportError("partnership_endpoint_https_required")
    hostname = str(parsed.hostname or "")
    port = parsed.port or 443
    address = sorted(target["resolved_addresses"])[0]
    raw_socket = socket.create_connection((address, port), timeout=5)
    connection = None
    try:
        context = ssl.create_default_context()
        tls_socket = context.wrap_socket(raw_socket, server_hostname=hostname)
        peer = str(tls_socket.getpeername()[0])
        if peer != address or not ipaddress.ip_address(peer).is_global:
            raise GOIAPartnershipTransportError("connected_peer_resolution_mismatch")
        connection = http.client.HTTPSConnection(
            hostname,
            port=port,
            timeout=15,
            context=context,
        )
        connection.sock = tls_socket
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        declared = response.getheader("content-length")
        if declared:
            try:
                if int(declared) > MAX_ACK_BYTES:
                    raise GOIAPartnershipTransportError("acknowledgement_too_large")
            except ValueError as exc:
                raise GOIAPartnershipTransportError(
                    "invalid_acknowledgement_length"
                ) from exc
        response_body = response.read(MAX_ACK_BYTES + 1)
        if len(response_body) > MAX_ACK_BYTES:
            raise GOIAPartnershipTransportError("acknowledgement_too_large")
        return (
            response.status,
            {key.lower(): value for key, value in response.getheaders()},
            response_body,
        )
    finally:
        if connection is not None:
            connection.close()
        else:
            raw_socket.close()


def send_partnership_proposal(
    claimed: dict[str, Any],
    *,
    session=None,
    now: int | None = None,
) -> dict[str, Any]:
    endpoint = str(claimed.get("endpoint") or "")
    payload = claimed.get("payload")
    if not isinstance(payload, dict) or endpoint != str(payload.get("request_endpoint") or ""):
        return {
            "delivered": False,
            "retryable": False,
            "error_code": "claimed_endpoint_payload_mismatch",
        }
    try:
        target = validate_public_runtime_url(endpoint)
        body, headers = build_signed_request(payload, now=now)
        if session is None:
            status_code, response_headers, response_body = _post_pinned_https(
                endpoint,
                target=target,
                body=body,
                headers=headers,
            )
        else:
            response = session.post(
                endpoint,
                data=body,
                headers=headers,
                timeout=(5, 15),
                allow_redirects=False,
                stream=True,
            )
            _validate_connected_peer(response, target)
            status_code = response.status_code
            response_headers = {
                key.lower(): value for key, value in response.headers.items()
            }
            response_body = _read_bounded(response)
        if 300 <= status_code < 400:
            raise GOIAPartnershipTransportError("redirect_not_followed")
        if status_code < 200 or status_code >= 300:
            return {
                "delivered": False,
                "retryable": status_code == 429 or status_code >= 500,
                "error_code": f"unexpected_http_status_{status_code}",
            }
        content_type = response_headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in {"application/json", "application/ld+json"}:
            raise GOIAPartnershipTransportError("acknowledgement_json_required")
        acknowledgement = PartnershipAcknowledgement.model_validate_json(
            response_body
        )
        if acknowledgement.proposal_id != payload["proposal_id"]:
            raise GOIAPartnershipTransportError("acknowledgement_proposal_mismatch")
        return {
            "delivered": True,
            "retryable": False,
            "receipt": acknowledgement.model_dump(mode="json"),
        }
    except UnsafeNetworkTarget as exc:
        return {"delivered": False, "retryable": False, "error_code": str(exc)}
    except GOIAPartnershipTransportError as exc:
        return {"delivered": False, "retryable": False, "error_code": str(exc)}
    except (OSError, ssl.SSLError, requests.RequestException, ValidationError):
        return {
            "delivered": False,
            "retryable": True,
            "error_code": "transport_or_acknowledgement_failure",
        }
