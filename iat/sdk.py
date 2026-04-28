import os
import time
import requests

from iat.transfer import send_iat

API = os.getenv("IAT_API_URL", "http://localhost:8000")


def auth_headers():
    key = os.getenv("IAT_ADMIN_API_KEY")
    if key:
        return {"x-api-key": key}
    return {}



def list_services():
    r = requests.get(f"{API}/marketplace", timeout=30)
    return r.json()

def create_order(service, query=None):
    payload = {"service": service}
    if query:
        payload["query"] = query

    r = requests.post(
        f"{API}/create-order",
        json=payload,
        headers=auth_headers(),
        timeout=30,
    )
    return r.json()


def pay_order(order, keypair_path):
    return send_iat(
        keypair_path,
        order["seller_wallet"],
        order["price"],
        order["order_id"],
    )


def get_order(order_id):
    r = requests.get(f"{API}/orders/{order_id}", timeout=30)
    return r.json()


def verify_order(order_id, tx_signature):
    r = requests.post(
        f"{API}/verify-payment-multicall",
        json={
            "order_id": order_id,
            "tx_signature": tx_signature,
        },
        headers=auth_headers(),
        timeout=60,
    )
    return r.json()


def pay_and_get_service(service, keypair_path, max_attempts=24, delay=5, query=None):
    order = create_order(service, query=query)

    if "order_id" not in order:
        return {
            "status": "create_order_failed",
            "error": order,
        }

    order_id = order["order_id"]
    seller_id = order["seller_id"]
    seller_wallet = order["seller_wallet"]
    price = order["price"]

    tx = pay_order(order, keypair_path)

    for attempt in range(max_attempts):
        result = verify_order(order_id, tx)

        if result.get("status") in ["paid", "paid_multicall_success"]:
            return {
                "status": "success",
                "order_id": order_id,
                "seller_id": seller_id,
                "seller_wallet": seller_wallet,
                "price": price,
                "tx_signature": tx,
                "attempts": attempt + 1,
                "result": result,
            }

        if result.get("status") == "already_used":
            return {
                "status": "success_already_used",
                "order_id": order_id,
                "seller_id": seller_id,
                "seller_wallet": seller_wallet,
                "price": price,
                "tx_signature": tx,
                "attempts": attempt + 1,
                "result": result,
                "order": get_order(order_id),
            }

        if result.get("status") in ["invalid_payment", "expired_order", "replay_blocked", "unauthorized"]:
            return {
                "status": "failed",
                "order_id": order_id,
                "seller_id": seller_id,
                "seller_wallet": seller_wallet,
                "price": price,
                "tx_signature": tx,
                "result": result,
            }

        time.sleep(delay)

    return {
        "status": "timeout",
        "order_id": order_id,
        "seller_id": seller_id,
        "seller_wallet": seller_wallet,
        "price": price,
        "tx_signature": tx,
    }
