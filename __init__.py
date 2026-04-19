# IAT Protocol SDK
# © molamoh 2026 — All rights reserved
# github.com/molamoh/iat-protocol

from .wallet import IATWallet, create_wallet, get_network_stats
from .verifai import VerifAI
from .protocol import PoAITProtocol
from .config import IAT_TOKEN_ADDRESS, IAT_VERSION

__version__ = "1.0.0"
__author__ = "Anonymous Founder — molamoh"
__token__ = IAT_TOKEN_ADDRESS

print(f"IAT Protocol SDK v{__version__} — The machine economy starts here. 🤖")
