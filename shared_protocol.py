import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List

LEDGER_FILE = Path("iat_ledger_v2.json")
WALLETS_FILE = Path("iat_wallets_v2.json")


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Transaction:
    tx_id: str
    sender: str
    receiver: str
    amount: float
    memo: str
    timestamp_ms: int
    status: str = "confirmed"


@dataclass
class Wallet:
    agent_id: str
    address: str = field(default_factory=lambda: secrets.token_hex(16))
    balance: float = 0.0
    certified: bool = False


class WalletStore:
    def __init__(self, path: Path = WALLETS_FILE):
        self.path = path
        self.wallets: Dict[str, Wallet] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.wallets = {k: Wallet(**v) for k, v in data.items()}

    def _save(self):
        payload = {k: asdict(v) for k, v in self.wallets.items()}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def create_wallet(self, agent_id: str) -> Wallet:
        wallet = Wallet(agent_id=agent_id)
        self.wallets[agent_id] = wallet
        self._save()
        return wallet

    def get_wallet(self, agent_id: str) -> Wallet:
        return self.wallets[agent_id]

    def upsert_wallet(self, wallet: Wallet):
        self.wallets[wallet.agent_id] = wallet
        self._save()


class VerifAI:
    def __init__(self):
        self.registry: Dict[str, str] = {}

    def certify(self, wallet: Wallet, model_name: str) -> str:
        fingerprint = hashlib.sha256(
            f"{wallet.agent_id}:{model_name}:{wallet.address}".encode()
        ).hexdigest()
        self.registry[wallet.address] = fingerprint
        wallet.certified = True
        return fingerprint

    def is_certified(self, wallet: Wallet) -> bool:
        return wallet.certified


class IATProtocol:
    def __init__(self, fee_percent: float = 1.0, burn_percent: float = 10.0):
        self.fee_percent = fee_percent
        self.burn_percent = burn_percent
        self.transactions: List[Transaction] = []
        self.total_burned = 0.0
        self.total_fees = 0.0
        self._load_ledger()

    def _load_ledger(self):
        if LEDGER_FILE.exists():
            data = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
            self.total_burned = data.get("total_burned", 0.0)
            self.total_fees = data.get("total_fees", 0.0)
            self.transactions = [Transaction(**item) for item in data.get("transactions", [])]

    def _save_ledger(self):
        payload = {
            "total_burned": self.total_burned,
            "total_fees": self.total_fees,
            "transactions": [asdict(tx) for tx in self.transactions],
        }
        LEDGER_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def faucet(self, wallet: Wallet, amount: float, memo: str = "initial funding") -> Transaction:
        wallet.balance += amount
        tx = Transaction(
            tx_id=self._make_tx_id("SYSTEM", wallet.address, amount, memo),
            sender="SYSTEM",
            receiver=wallet.address,
            amount=amount,
            memo=memo,
            timestamp_ms=now_ms(),
        )
        self.transactions.append(tx)
        self._save_ledger()
        return tx

    def transfer(self, sender: Wallet, receiver: Wallet, amount: float, memo: str = "") -> Transaction:
        if not sender.certified:
            raise PermissionError(f"{sender.agent_id} non certifié")
        if not receiver.certified:
            raise PermissionError(f"{receiver.agent_id} non certifié")
        if amount <= 0:
            raise ValueError("Le montant doit être > 0")
        if sender.balance < amount:
            raise ValueError("Solde insuffisant")

        fee = amount * (self.fee_percent / 100)
        burned = fee * (self.burn_percent / 100)
        net_to_receiver = amount - fee

        sender.balance -= amount
        receiver.balance += net_to_receiver
        self.total_fees += fee
        self.total_burned += burned

        tx = Transaction(
            tx_id=self._make_tx_id(sender.address, receiver.address, amount, memo),
            sender=sender.address,
            receiver=receiver.address,
            amount=amount,
            memo=memo,
            timestamp_ms=now_ms(),
        )
        self.transactions.append(tx)
        self._save_ledger()
        return tx

    def _make_tx_id(self, sender: str, receiver: str, amount: float, memo: str) -> str:
        payload = f"{sender}:{receiver}:{amount}:{memo}:{time.time_ns()}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def stats(self) -> Dict[str, float]:
        return {
            "transactions_count": len(self.transactions),
            "total_fees": round(self.total_fees, 6),
            "total_burned": round(self.total_burned, 6),
        }