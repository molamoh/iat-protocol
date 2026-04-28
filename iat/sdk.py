import time
import requests
from iat.transfer import send_iat

import os
API = os.getenv("IAT_API_URL", "https://iat-protocol.onrender.com")


def list_services():
    r = requests.get(f"{API}/services")
    r.raise_for_status()
    return r.json()


def create_order(service, query=None):
    payload = {"service": service}
    if query:
        payload["query"] = query
    r = requests.post(f"{API}/create-order", json=payload)
    r.raise_for_status()
    return r.json()


def pay_order(keypair_path, wallet_to, amount, order_id):
    return send_iat(keypair_path, wallet_to, amount, order_id)


def verify_order(order_id, tx_signature):
    try:
        r = requests.post(f"{API}/verify-payment-multicall", json={
            "order_id": order_id,
            "tx_signature": tx_signature
        }, timeout=30)

        if r.status_code >= 500:
            return {"status": "server_error", "code": r.status_code}

        r.raise_for_status()
        return r.json()

    except requests.exceptions.RequestException as e:
        return {"status": "network_error", "error": str(e)}


def pay_and_get_service(service, keypair_path, max_attempts=12, delay=5, query=None):
    order = create_order(service, query=query)

    if order.get("status") in ["unknown_service", "no_seller_available"]:
        return {"status": "failed", "reason": order}

    order_id = order["order_id"]
    price = order["price"]
    seller_wallet = order["seller_wallet"]
    seller_id = order.get("seller_id")

    tx = pay_order(
        keypair_path=keypair_path,
        wallet_to=seller_wallet,
        amount=price,
        order_id=order_id
    )

    for attempt in range(1, max_attempts + 1):
        result = verify_order(order_id, tx)

        if result.get("status") in ["paid", "paid_multicall_success"]:
            return {
                "status": "success",
                "order_id": order_id,
                "seller_id": seller_id,
                "seller_wallet": seller_wallet,
                "price": price,
                "tx_signature": tx,
                "attempts": attempt,
                "result": result
            }

        if result.get("status") in ["invalid_payment", "expired", "replay_blocked", "order_already_used"]:
            return {
                "status": "failed",
                "order_id": order_id,
                "seller_id": seller_id,
                "tx_signature": tx,
                "reason": result
            }

        time.sleep(delay)

    return {
        "status": "timeout",
        "order_id": order_id,
        "seller_id": seller_id,
        "seller_wallet": seller_wallet,
        "price": price,
        "tx_signature": tx
    }
