"""Network target validation used before contacting third-party runtimes."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


class UnsafeNetworkTarget(ValueError):
    """A URL could expose the protocol to SSRF or insecure transport."""


def validate_public_runtime_url(url: str) -> dict:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeNetworkTarget("invalid_runtime_scheme")
    if not parsed.hostname:
        raise UnsafeNetworkTarget("runtime_hostname_required")
    if parsed.username or parsed.password:
        raise UnsafeNetworkTarget("runtime_url_credentials_not_allowed")
    if parsed.fragment:
        raise UnsafeNetworkTarget("runtime_url_fragment_not_allowed")
    allow_insecure = os.getenv("IAT_ALLOW_INSECURE_SELLER_RUNTIME", "false").lower() == "true"
    if parsed.scheme != "https" and not allow_insecure:
        raise UnsafeNetworkTarget("https_runtime_required")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                parsed.hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise UnsafeNetworkTarget("runtime_hostname_resolution_failed") from exc

    if not addresses:
        raise UnsafeNetworkTarget("runtime_hostname_resolution_failed")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeNetworkTarget("runtime_target_must_be_public")

    return {
        "scheme": parsed.scheme,
        "hostname": parsed.hostname.lower(),
        "port": port,
        "resolved_addresses": sorted(addresses),
        "public": True,
        "credentials_present": False,
    }
