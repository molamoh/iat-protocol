import os
import time
import requests

from iat.transfer import send_iat


API = os.getenv("IAT_API_URL", "http://localhost:8000")


def auth_headers():
    key = os.getenv("IAT_ADMIN_API_KEY")
    return {"x-api-key": key} if key else {}


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



def post_with_retry(url, json=None, headers=None, timeout=60, retries=3, delay=2):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                url,
                json=json,
                headers=headers,
                timeout=timeout,
            )

            if r.status_code >= 500 and attempt < retries:
                print(f"⚠️ API server error {r.status_code}, retry {attempt}/{retries}")
                time.sleep(delay)
                continue

            return r

        except Exception as e:
            last_error = str(e)
            print(f"⚠️ Request failed, retry {attempt}/{retries}: {last_error}")
            if attempt < retries:
                time.sleep(delay)

    return {
        "status": "error",
        "message": "request_failed_after_retries",
        "error": last_error,
    }


def list_services():
    r = requests.get(f"{API}/services", headers=auth_headers(), timeout=30)
    return safe_json_response(r)


def create_order(service, query=None):
    r = post_with_retry(
        f"{API}/create-order",
        json={"service": service, "query": query},
        headers=auth_headers(),
        timeout=30,
        retries=3,
        delay=2,
    )

    if isinstance(r, dict):
        return r

    return safe_json_response(r)


def pay_order(order, keypair_path):
    seller_wallet = order["seller_wallet"]
    price = float(order["price"])
    order_id = order.get("order_id")

    return send_iat(
        keypair_path,
        seller_wallet,
        price,
        memo=order_id,
    )


def verify_order(order_id, tx_signature):
    r = post_with_retry(
        f"{API}/verify-payment-multicall",
        json={
            "order_id": order_id,
            "tx_signature": tx_signature,
        },
        headers=auth_headers(),
        timeout=60,
        retries=3,
        delay=2,
    )

    if isinstance(r, dict):
        return r

    return safe_json_response(r)


def pay_and_get_service(service, keypair_path, max_attempts=24, delay=5, query=None):
    order = create_order(service, query=query)

    if "order_id" not in order:
        return {
            "status": "create_order_failed",
            "error": order,
        }

    order_id = order["order_id"]
    buyer_secret = order.get("buyer_secret")
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
                "buyer_secret": buyer_secret,
                "seller_id": seller_id,
                "seller_wallet": seller_wallet,
                "price": price,
                "tx_signature": tx,
                "attempts": attempt + 1,
                "result": result,
            }

        time.sleep(delay)

    return {
        "status": "timeout",
        "order_id": order_id,
        "tx_signature": tx,
    }
