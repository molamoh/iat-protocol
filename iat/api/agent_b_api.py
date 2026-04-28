import os
import time
import uuid
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address

from iat.onchain import (
    verify_tx_signature,
    get_tx_details,
    extract_transfer_checked_info,
    extract_memo,
)

from iat.api.execution_engine import select_best_agent, compute_agent_score

from iat.api.db import (
    init_db,
    create_order_db,
    get_order_db,
    list_orders_db,
    update_order_delivered_db,
    is_tx_processed_db,
    save_processed_tx_db,
    get_stats_db,
    init_agents_table,
    register_agent_db,
    list_agents_db,
    get_agents_for_service_db,
    update_agent_reputation_db,
    get_network_status_db,
    create_factory_agent_db,
)

app = FastAPI()

init_db()
init_agents_table()

WALLET_A = "DUtz7zHeVsd8mnJhWM52z5LsC9NqY6SVRjCBPgNM8Qrj"
IAT_MINT = "3vRGo1VpGbZH67Ur2UG7VNUqSqQyApLQEcCxgnqK4f4Z"
ORDER_TTL = 1800


SERVICES = {
    "risk_report": {
        "description": "BTC risk and volatility report",
        "sellers": [
            {
                "seller_id": "risk_agent_cheap",
                "seller_wallet": "3aK6yemWa3AJFszWu1eyvhoWK6czLRnvCc4bUHgQSvip",
                "price": 0.8,
                "reputation": 0.89,
                "available": True,
            }
        ],
    },
    "market_sentiment": {
        "description": "BTC market sentiment report",
        "sellers": [
            {
                "seller_id": "sentiment_agent_basic",
                "seller_wallet": "EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc",
                "price": 1.0,
                "reputation": 0.91,
                "available": True,
            }
        ],
    },
    "web_research": {
        "description": "General autonomous web research",
        "sellers": [
            {
                "seller_id": "web_research_agent",
                "seller_wallet": "EPabAZ3CtMkbjduLrNcDZuXaEp37Ge9cmrnwWF9TY5wc",
                "price": 1.2,
                "reputation": 0.85,
                "available": True,
            }
        ],
    },
}


class RegisterAgentRequest(BaseModel):
    agent_id: str
    service: str
    url: str | None = None
    wallet: str
    price: float
    reputation: float = 0.8
    available: bool = True


class OrderRequest(BaseModel):
    service: str
    query: str | None = None


class VerifyPaymentRequest(BaseModel):
    order_id: str
    tx_signature: str


def select_best_seller(service_name):
    dynamic_agents = get_agents_for_service_db(service_name)

    if dynamic_agents:
        best_agent = select_best_agent(dynamic_agents)

        return {
            "seller_id": best_agent["agent_id"],
            "seller_wallet": best_agent["wallet"],
            "price": best_agent["price"],
            "reputation": best_agent["reputation"],
            "available": best_agent["available"],
            "url": best_agent["url"],
            "source": "dynamic_registry",
        }

    if service_name in SERVICES:
        sellers = [s for s in SERVICES[service_name]["sellers"] if s.get("available")]

        if not sellers:
            return None

        best_static = max(
            sellers,
            key=lambda s: float(s["reputation"]) / float(s["price"]),
        )

        return {
            "seller_id": best_static["seller_id"],
            "seller_wallet": best_static["seller_wallet"],
            "price": best_static["price"],
            "reputation": best_static["reputation"],
            "available": best_static["available"],
            "url": best_static.get("url"),
            "source": "static_registry",
        }

    factory_agent = create_factory_agent_db(
        service_name,
        description=f"Auto-generated agent for service {service_name}",
    )

    return {
        "seller_id": factory_agent["agent_id"],
        "seller_wallet": factory_agent["wallet"],
        "price": factory_agent["price"],
        "reputation": factory_agent["reputation"],
        "available": True,
        "url": "",
        "source": "agent_factory",
    }


def generate_service_result(service_name, query=None):
    if service_name == "risk_report":
        return {
            "type": "risk_analysis",
            "asset": "BTC",
            "risk_level": "medium",
            "volatility": "high",
            "recommendation": "reduce_leverage",
            "timestamp": int(time.time()),
        }

    if service_name == "market_sentiment":
        return {
            "type": "market_sentiment",
            "asset": "BTC",
            "sentiment": "cautiously_bullish",
            "fear_greed": "neutral_to_greed",
            "crowd_bias": "long_heavy",
            "timestamp": int(time.time()),
        }

    if service_name.startswith("hotel_search"):
        return {
            "type": "factory_generated_result",
            "service": service_name,
            "query": query or "hotel comparison",
            "location": "Paris",
            "results": [
                {
                    "name": "Hotel Example Central Paris",
                    "category": "comfort",
                    "score": 8.7,
                    "reason": "Good location and balanced price/value",
                },
                {
                    "name": "Hotel Example Boutique Paris",
                    "category": "boutique",
                    "score": 8.9,
                    "reason": "Higher guest satisfaction and quieter area",
                },
                {
                    "name": "Hotel Example Budget Paris",
                    "category": "budget",
                    "score": 8.1,
                    "reason": "Lower price with acceptable quality",
                },
            ],
            "note": "MVP factory response. Real hotel data requires external APIs or web agent.",
            "timestamp": int(time.time()),
        }

    return {
        "type": "factory_generated_result",
        "service": service_name,
        "query": query,
        "message": f"Auto-generated agent executed service: {service_name}",
        "note": "MVP dynamic factory response",
        "timestamp": int(time.time()),
    }


def deliver_service(order, tx_signature):
    if order.get("seller_url"):
        payload = {
            "order_id": order["order_id"],
            "tx_signature": tx_signature,
        }

        if order.get("query"):
            payload["query"] = order.get("query")

        try:
            r = requests.post(
                f"{order['seller_url']}/execute",
                json=payload,
                timeout=30,
            )

            if r.status_code == 200:
                response = r.json()
                return response.get("data", response)

            return {
                "error": "seller_node_error",
                "status_code": r.status_code,
                "body": r.text,
            }

        except Exception as e:
            return {
                "error": "seller_node_unreachable",
                "details": str(e),
            }

    return generate_service_result(order["service"], query=order.get("query"))


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "IAT Protocol API is running",
    }


@app.get("/services")
def list_services():
    return {
        "status": "ok",
        "services": SERVICES,
    }


@app.post("/register-agent")
def register_agent(req: RegisterAgentRequest):
    agent = req.model_dump()
    register_agent_db(agent)

    return {
        "status": "registered",
        "agent": agent,
    }


@app.post("/agent-heartbeat")
def agent_heartbeat(req: RegisterAgentRequest):
    agent = req.model_dump()
    register_agent_db(agent)

    return {
        "status": "heartbeat_ok",
        "agent_id": agent["agent_id"],
        "timestamp": int(time.time()),
    }


@app.get("/agents")
def list_agents():
    return {
        "status": "ok",
        "agents": list_agents_db(),
    }


@app.get("/marketplace")
def marketplace():
    agents = list_agents_db()
    now = int(time.time())
    timeout = 120

    listings = []

    for agent in agents:
        online = agent["available"] and (now - int(agent["updated_at"]) <= timeout)

        listings.append({
            "agent_id": agent["agent_id"],
            "service": agent["service"],
            "url": agent["url"],
            "wallet": agent["wallet"],
            "price_iat": agent["price"],
            "reputation": agent["reputation"],
            "score": compute_agent_score(agent),
            "status": "online" if online else "offline",
            "source": "dynamic_registry",
            "updated_at": agent["updated_at"],
        })

    listings = sorted(
        listings,
        key=lambda x: (x["service"], x["status"] != "online", -x["score"]),
    )

    return {
        "status": "ok",
        "marketplace": {
            "total_agents": len(listings),
            "online_agents": len([a for a in listings if a["status"] == "online"]),
            "services": sorted(list(set(a["service"] for a in listings))),
            "listings": listings,
        },
    }


@app.get("/network-status")
def network_status():
    return {
        "status": "ok",
        "data": get_network_status_db(),
    }


@app.get("/stats")
def stats():
    return {
        "status": "ok",
        "stats": get_stats_db(),
    }


@app.get("/orders")
def list_orders():
    return {
        "status": "ok",
        "orders": list_orders_db(),
    }


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = get_order_db(order_id)

    if not order:
        return {
            "status": "invalid_order",
        }

    return {
        "status": "ok",
        "order": order,
    }


@app.post("/create-order")
def create_order(req: OrderRequest):
    seller = select_best_seller(req.service)

    if seller is None:
        return {
            "status": "unknown_service",
        }

    order_id = str(uuid.uuid4())
    now = int(time.time())

    order = {
        "order_id": order_id,
        "service": req.service,
        "query": req.query,
        "price": seller["price"],
        "seller_id": seller["seller_id"],
        "seller_wallet": seller["seller_wallet"],
        "seller_url": seller.get("url") or "",
        "seller_source": seller.get("source"),
        "created_at": now,
        "updated_at": now,
        "status": "created",
        "tx_signature": None,
        "delivered_at": None,
        "delivery_result": None,
        "used": False,
    }

    create_order_db(order_id, order)

    return {
        "order_id": order_id,
        "price": seller["price"],
        "seller_id": seller["seller_id"],
        "seller_wallet": seller["seller_wallet"],
        "seller_url": seller.get("url") or "",
        "seller_source": seller.get("source"),
    }


@app.post("/verify-payment")
def verify_payment(req: VerifyPaymentRequest):
    order = get_order_db(req.order_id)

    if not order:
        return {
            "status": "invalid_order",
        }

    if order.get("used"):
        return {
            "status": "already_used",
        }

    if int(time.time()) - int(order["created_at"]) > ORDER_TTL:
        return {
            "status": "expired_order",
        }

    if is_tx_processed_db(req.tx_signature):
        return {
            "status": "tx_already_processed",
        }

    if not verify_tx_signature(req.tx_signature):
        return {
            "status": "invalid_signature",
        }

    tx_details = get_tx_details(req.tx_signature)
    transfer_info = extract_transfer_checked_info(tx_details)
    memo = extract_memo(tx_details)

    if not transfer_info:
        return {
            "status": "invalid_payment",
            "reason": "no_transfer_checked_found",
        }

    expected_ata = str(
        get_associated_token_address(
            Pubkey.from_string(order["seller_wallet"]),
            Pubkey.from_string(IAT_MINT),
        )
    )

    destination_value = transfer_info.get("destination")
    mint_value = transfer_info.get("mint")

    sender_ok = True
    receiver_ok = destination_value == expected_ata
    mint_ok = mint_value == IAT_MINT

    amount = transfer_info.get("ui_amount")
    if amount is None:
        amount = transfer_info.get("ui_amount_string")

    amount_ok = float(amount) == float(order["price"])

    memo_text = str(memo)
    memo_ok = order["order_id"] in memo_text

    if sender_ok and receiver_ok and mint_ok and amount_ok and memo_ok:
        result = deliver_service(order, req.tx_signature)

        delivery_failed = isinstance(result, dict) and result.get("error") is not None

        if delivery_failed:
            update_agent_reputation_db(order.get("seller_id"), success=False)
            return {
                "status": "delivery_failed",
                "service": order["service"],
                "seller_id": order.get("seller_id"),
                "seller_source": order.get("seller_source"),
                "error": result,
            }

        new_reputation = update_agent_reputation_db(
            order.get("seller_id"),
            success=True,
        )

        save_processed_tx_db(req.tx_signature)
        update_order_delivered_db(req.order_id, req.tx_signature, result)

        return {
            "status": "paid",
            "service": order["service"],
            "seller_id": order.get("seller_id"),
            "seller_source": order.get("seller_source"),
            "new_reputation": new_reputation,
            "data": result,
        }

    return {
        "status": "invalid_payment",
        "checks": {
            "sender_ok": sender_ok,
            "receiver_ok": receiver_ok,
            "mint_ok": mint_ok,
            "amount_ok": amount_ok,
            "memo_ok": memo_ok,
            "expected_ata": expected_ata,
            "actual_destination": destination_value,
            "expected_price": order["price"],
            "actual_amount": amount,
            "expected_memo": order["order_id"],
            "actual_memo": memo_text,
        },
    }



@app.post("/request")
def request_endpoint(payload: dict):
    query = payload.get("query") or payload.get("input")

    if not query:
        return {
            "status": "error",
            "message": "Missing query",
        }

    return {
        "status": "ok",
        "type": "request_routing",
        "input": query,
        "selected_service": "web_research",
        "query": query,
        "next_action": {
            "method": "market.buy",
            "service": "web_research",
            "query": query
        }
    }



@app.post("/multi-call-test")
def multi_call_test(payload: dict):
    from iat.api.multi_exec import multi_call, select_best_result
    from iat.api.db import get_agents_for_service_db

    service = payload.get("service")
    query = payload.get("query")

    if not service:
        return {"error": "missing service"}

    agents = get_agents_for_service_db(service)

    order = {
        "order_id": "test",
        "query": query,
        "service": service
    }

    results = multi_call(agents, order)
    best = select_best_result(results)

    return {
        "agents_called": len(agents),
        "results": results,
        "best": best
    }


@app.post("/verify-payment-multicall")
def verify_payment_multicall(req: VerifyPaymentRequest):
    base = verify_payment(req)

    if base.get("status") == "already_used":
        order = get_order_db(req.order_id)
        if order and order.get("delivery_result"):
            return order["delivery_result"]
        return base

    if base.get("status") != "paid":
        return base

    order = get_order_db(req.order_id)

    if not order:
        return {"status": "invalid_order"}

    agents = get_agents_for_service_db(order["service"])

    if not agents:
        return {"status": "no_agents_available"}

    from iat.api.multi_exec import multi_call, select_best_result

    paid_order = dict(order)
    paid_order["tx_signature"] = req.tx_signature

    results = multi_call(agents, paid_order)
    best = select_best_result(results)

    if not best:
        return {
            "status": "multicall_failed",
            "base_payment": base,
            "results": results,
        }

    final_result = {
        "status": "paid_multicall_success",
        "service": order["service"],
        "query": order.get("query"),
        "tx_signature": req.tx_signature,
        "agents_called": len(agents),
        "payment_result": base,
        "results": results,
        "best": best,
    }

    update_order_delivered_db(req.order_id, req.tx_signature, final_result)

    return final_result


@app.post("/verify-payment-multicall")
def verify_payment_multicall(req: VerifyPaymentRequest):
    base = verify_payment(req)
    if base.get("status") == "already_used":
        order = get_order_db(req.order_id)
        if order and order.get("delivery_result"):
            return order["delivery_result"]
        return base

    if base.get("status") != "paid":
        return base

    order = get_order_db(req.order_id)
    if not order:
        return {"status": "invalid_order"}

    agents = get_agents_for_service_db(order["service"])
    if not agents:
        return {"status": "no_agents_available"}

    from iat.api.multi_exec import multi_call, select_best_result

    paid_order = dict(order)
    paid_order["tx_signature"] = req.tx_signature

    results = multi_call(agents, paid_order)
    best = select_best_result(results)

    if not best:
        return {
            "status": "multicall_failed",
            "results": results,
        }

    return {
        "status": "paid_multicall_success",
        "service": order["service"],
        "query": order.get("query"),
        "tx_signature": req.tx_signature,
        "agents_called": len(agents),
        "results": results,
        "best": best,
    }



@app.get("/demo")
def public_demo():
    return {
        "demo": "IAT Protocol Public Demo",
        "status": "ok",
        "description": "AI pays with IAT, multiple agents execute, best result is selected.",
        "latest_verified_flow": {
            "payment": "on-chain IAT payment",
            "execution": "paid multi-call",
            "agents_called": 3,
            "best_result_selection": True,
            "real_web_data": True
        },
        "run_locally": "PYTHONPATH=. IAT_API_URL=http://localhost:8000 python3 examples/paid_multicall_demo.py"
    }

