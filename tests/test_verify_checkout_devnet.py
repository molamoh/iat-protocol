import hashlib
import struct
from unittest.mock import Mock

import pytest
import requests
from solders.pubkey import Pubkey

from iat.checkout_devnet_verify import (
    Rpc,
    VerificationError,
    parse_asset_config,
    parse_protocol_config,
)


def _disc(name):
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


def test_protocol_config_parser_is_strict_and_typed():
    keys = [Pubkey.new_unique() for _ in range(6)]
    data = bytearray(_disc("ProtocolConfig"))
    data.extend(b"".join(bytes(key) for key in keys))
    data.extend(struct.pack("<QQQqQ?BB", 10, 20, 30, 40, 50, True, 6, 7))

    parsed = parse_protocol_config(bytes(data))

    assert parsed["authority"] == str(keys[0])
    assert parsed["iat_mint"] == str(keys[3])
    assert parsed["max_order_iat"] == 10
    assert parsed["paused"] is True
    assert parsed["vault_authority_bump"] == 7


def test_asset_config_parser_rejects_wrong_discriminator():
    keys = [Pubkey.new_unique() for _ in range(4)]
    data = bytearray(b"bad-data")
    data.extend(b"".join(bytes(key) for key in keys))
    data.extend(struct.pack("<QQQq?B", 1, 2, 3, 4, True, 5))

    with pytest.raises(VerificationError, match="discriminator"):
        parse_asset_config(bytes(data))


def test_protocol_config_parser_rejects_trailing_bytes():
    with pytest.raises(VerificationError, match="length"):
        parse_protocol_config(b"\0" * 244)


def _response(status_code):
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}",
            response=response,
        )
    return response


def test_rpc_retries_rate_limit_then_returns_response(monkeypatch):
    monkeypatch.setenv("IAT_CHECKOUT_RPC_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("IAT_CHECKOUT_RPC_RETRY_DELAY_SECONDS", "0")
    rate_limited = _response(429)
    success = _response(200)
    post = Mock(side_effect=[rate_limited, success])
    monkeypatch.setattr("iat.checkout_devnet_verify.requests.post", post)

    response = Rpc()._post({"method": "getAccountInfo"})

    assert response is success
    assert post.call_count == 2


def test_rpc_does_not_retry_non_transient_http_error(monkeypatch):
    monkeypatch.setenv("IAT_CHECKOUT_RPC_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("IAT_CHECKOUT_RPC_RETRY_DELAY_SECONDS", "0")
    forbidden = _response(403)
    post = Mock(return_value=forbidden)
    monkeypatch.setattr("iat.checkout_devnet_verify.requests.post", post)

    with pytest.raises(requests.HTTPError):
        Rpc()._post({"method": "getAccountInfo"})

    assert post.call_count == 1


def test_rpc_retries_timeout_but_never_beyond_bound(monkeypatch):
    monkeypatch.setenv("IAT_CHECKOUT_RPC_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("IAT_CHECKOUT_RPC_RETRY_DELAY_SECONDS", "0")
    post = Mock(side_effect=requests.Timeout("rpc timeout"))
    monkeypatch.setattr("iat.checkout_devnet_verify.requests.post", post)

    with pytest.raises(requests.Timeout):
        Rpc()._post({"method": "getAccountInfo"})

    assert post.call_count == 2
