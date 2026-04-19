# IAT Protocol — Wallet Management
# © molamoh 2026 — All rights reserved

import time
import hashlib
import secrets
from typing import Optional
from .config import IAT_TOKEN_ADDRESS, IAT_NETWORK, IAT_VERSION
from .verifai import VerifAI
from .protocol import PoAITProtocol

_protocol = PoAITProtocol()

class IATWallet:
    def __init__(self, agent_id: str, agent_type: str = "AI_AGENT"):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.balance = 0.0
        self.transactions = []
        self.certified = False
        self._protocol = _protocol
        self._verifai = _protocol.verifai

    def certify(self) -> dict:
        challenge = self._verifai.generate_challenge()
        response = {
            "timestamp": challenge["timestamp"],
            "challenges_solved": len(challenge["challenges"]),
            "agent_id": self.agent_id
        }
        success = self._verifai.verify_agent(self.agent_id, response)
        if success:
            self.certified = True
            certificate = self._verifai.get_certificate(self.agent_id)
            return {"success": True, "agent_id": self.agent_id, "certificate": certificate[:16] + "...", "message": "VerifAI certification successful"}
        return {"success": False, "message": "VerifAI certification failed"}

    def pay(self, to_agent: str, amount: float, metadata: dict = {}) -> dict:
        if not self.certified:
            return {"success": False, "error": "Wallet not VerifAI certified. Call certify() first.", "code": "CERT_001"}
        if amount <= 0:
            return {"success": False, "error": "Amount must be greater than 0", "code": "AMT_001"}
        if self.balance < amount:
            return {"success": False, "error": "Insufficient IAT balance", "code": "BAL_001"}
        result = self._protocol.submit_transaction(from_agent=self.agent_id, to_agent=to_agent, amount=amount, metadata=metadata)
        if result["success"]:
            self.balance -= amount
            self.transactions.append(result)
        return result

    def receive(self, amount: float, from_agent: str = "SYSTEM") -> dict:
        self.balance += amount
        tx = {"type": "received", "amount": amount, "from": from_agent, "timestamp": time.time()}
        self.transactions.append(tx)
        return {"success": True, "new_balance": self.balance}

    def get_balance(self) -> float:
        return self.balance

    def get_history(self) -> list:
        return self.transactions

    def get_info(self) -> dict:
        return {"agent_id": self.agent_id, "agent_type": self.agent_type, "balance": self.balance, "certified": self.certified, "token": IAT_TOKEN_ADDRESS, "network": IAT_NETWORK, "sdk_version": IAT_VERSION, "transactions_count": len(self.transactions)}


def create_wallet(agent_id: str, agent_type: str = "AI_AGENT") -> IATWallet:
    return IATWallet(agent_id=agent_id, agent_type=agent_type)

def get_network_stats() -> dict:
    return _protocol.get_network_stats()
