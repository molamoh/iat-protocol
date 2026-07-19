"""
IAT Public Platform.

Read-only exposure and observability layer for the IAT Protocol.
No business authority belongs in this package.
"""

from iat.platform.config import PLATFORM_VERSION
from iat.platform.explorer import build_protocol_explorer_snapshot
from iat.platform.gateway import build_public_platform_status
from iat.platform.graph import build_protocol_graph

__all__ = [
    "PLATFORM_VERSION",
    "build_protocol_explorer_snapshot",
    "build_public_platform_status",
    "build_protocol_graph",
]
