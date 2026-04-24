import time
import requests
from iat.transfer import send_iat

API = "https://iat-protocol.onrender.com"


def list_services():
    r = requests.get(f"{API}/services")
    return r.json()


def create_order(service):
    r = requests.post(f"{API}/create-order", json={"service": service})
    return r.json()


def pay_order(keypair_path, wallet_to, amount, order_id):
    return send_iat(keypair_path, wallet_to, amount, order_id)


def verify_order(order_id, tx_signature):
    r = requests.post(f"{API}/verify-payment", json={
        "order_id": order_id,
        "tx_signature": tx_signature
    })
    return r.json()


def get_service_info(service):
    services = list_services()["services"]

    if service not in services:
        raise ValueError(f"Unknown service: {service}")

    return services[service]


def pay_and_get_service(service, keypair_path, max_attempts=10):
    service_info = get_service_info(service)

    seller_wallet = service_info["seller_wallet"]

    order = create_order(service)

    order_id = order["order_id"]
    price = order["price"]

    tx = pay_order(
        keypair_path=keypair_path,
        wallet_to=seller_wallet,
        amount=price,
        order_id=order_id
    )

    for _ in range(max_attempts):
        result = verify_order(order_id, tx)

        if result.get("status") == "paid":
            return {
                "order_id": order_id,
                "tx_signature": tx,
                "service_info": service_info,
                "result": result
            }

        time.sleep(5)

    return {
        "order_id": order_id,
        "tx_signature": tx,
        "service_info": service_info,
        "result": {"status": "timeout"}
    }
