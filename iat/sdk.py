import requests
import os


API = os.getenv("IAT_API_URL", "http://localhost:8000")


def safe_json_response(r):
    if r.status_code != 200:
        print("\n❌ API ERROR")
        print("Status:", r.status_code)
        print("Response:", r.text[:500])

    try:
        return r.json()
    except Exception:
        print("\n❌ API RESPONSE NOT JSON")
        print("Status:", r.status_code)
        print("Response:", r.text[:1000])
        return {
            "status": "error",
            "http_status": r.status_code,
            "raw_response": r.text[:1000],
        }


def create_order(service, query=None):
    r = requests.post(
        f"{API}/create-order",
        json={
            "service": service,
            "query": query,
        },
        timeout=30,
    )
    return safe_json_response(r)


def verify_order(order_id, tx_signature):
    r = requests.post(
        f"{API}/verify-payment-multicall",
        json={
            "order_id": order_id,
            "tx_signature": tx_signature,
        },
        timeout=60,
    )
    return safe_json_response(r)


def pay_and_get_service(service, keypair_path, query=None):
    order = create_order(service, query=query)

    if order.get("status") != "ok":
        return order

    order_id = order["order_id"]

    # Simulation paiement (déjà géré ailleurs dans ton projet)
    tx_signature = "SIMULATED_TX"

    result = verify_order(order_id, tx_signature)

    return result
