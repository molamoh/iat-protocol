import time
import uuid
import json
import os
from fastapi import FastAPI
from pydantic import BaseModel

from iat.onchain import (
    verify_tx_signature,
    get_tx_details,
    extract_transfer_checked_info,
    extract_memo
)

app = FastAPI()

WALLET_A = "DUtz7zHeVsd8mnJhWM52z5LsC9NqY6SVRjCBPgNM8Qrj"
EXPECTED_ATA = "96SuCx9iyvp3uYXYAZSRxgMnoEL1gAE7DTjUKhUjKmSV"
IAT_MINT = "3vRGo1VpGbZH67Ur2UG7VNUqSqQyApLQEcCxgnqK4f4Z"
SERVICE_PRICE = 1.0
ORDER_TTL = 300

PROCESSED_TX_FILE = "api_processed_txs.json"
ORDERS_FILE = "api_orders.json"


class OrderRequest(BaseModel):
    service: str


class VerifyRequest(BaseModel):
    order_id: str
    tx_signature: str


def load_json_file(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        return json.load(f)


def save_json_file(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_processed_txs():
    return set(load_json_file(PROCESSED_TX_FILE, []))


def save_processed_tx(tx_signature):
    txs = load_processed_txs()
    txs.add(tx_signature)
    save_json_file(PROCESSED_TX_FILE, list(txs))


def load_orders():
    return load_json_file(ORDERS_FILE, {})


def save_orders(orders):
    save_json_file(ORDERS_FILE, orders)


@app.post("/create-order")
def create_order(req: OrderRequest):
    orders = load_orders()
    order_id = str(uuid.uuid4())

    orders[order_id] = {
        "service": req.service,
        "price": SERVICE_PRICE,
        "created_at": int(time.time()),
        "used": False
    }

    save_orders(orders)

    return {
        "order_id": order_id,
        "price": SERVICE_PRICE
    }


def is_fresh(order):
    age = int(time.time()) - order["created_at"]
    return age <= ORDER_TTL


@app.post("/verify-payment")
def verify_payment(req: VerifyRequest):
    processed_txs = load_processed_txs()
    orders = load_orders()

    if req.tx_signature in processed_txs:
        return {"status": "replay_blocked"}

    if req.order_id not in orders:
        return {"status": "invalid_order"}

    order = orders[req.order_id]

    if order.get("used"):
        return {"status": "order_already_used"}

    if not is_fresh(order):
        return {"status": "expired"}

    if not verify_tx_signature(req.tx_signature):
        return {"status": "not_confirmed"}

    tx_details = get_tx_details(req.tx_signature)
    if tx_details is None:
        return {"status": "no_details"}

    transfer_info = extract_transfer_checked_info(tx_details)
    memo = extract_memo(tx_details)

    if transfer_info is None:
        return {"status": "invalid_tx"}

    sender_ok = transfer_info["authority"] == WALLET_A
    receiver_ok = transfer_info["destination"] == EXPECTED_ATA
    mint_ok = transfer_info["mint"] == IAT_MINT
    amount_ok = transfer_info["ui_amount"] == "1.0" or transfer_info["ui_amount_string"] == "1"
    memo_ok = memo is not None and req.order_id in memo

    if sender_ok and receiver_ok and mint_ok and amount_ok and memo_ok:
        save_processed_tx(req.tx_signature)

        order["used"] = True
        orders[req.order_id] = order
        save_orders(orders)

        return {
            "status": "paid",
            "service": order["service"]
        }

    return {"status": "invalid_payment"}
