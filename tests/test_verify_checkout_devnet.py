import hashlib
import struct

import pytest
from solders.pubkey import Pubkey

from iat.checkout_devnet_verify import (
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
