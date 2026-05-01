import os
import time
import uuid
import requests
from fastapi import FastAPI, Header
from pydantic import BaseModel
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address
from iat.transfer import send_iat
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
    update_order_db,
)

app = FastAPI()


def payment_wallet_for(agent_wallet):
    escrow_wallet = os.getenv("IAT_ESCROW_WALLET")
    return escrow_wallet if escrow_wallet else agent_wallet


def payment_target():
    return "escrow" if os.getenv("IAT_ESCROW_WALLET") else "seller"


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
def create_order(req: OrderRequest, x_api_key: str | None = Header(default=None)):
    print("ESCROW ENV:", os.getenv("IAT_ESCROW_WALLET"))
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}
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
        "seller_wallet": payment_wallet_for(seller["seller_wallet"]),
        "actual_agent_wallet": seller["seller_wallet"],
        "payment_target": payment_target(),
        "seller_url": seller.get("url") or "",
        "seller_source": seller.get("source"),
        "created_at": now,
        "updated_at": now,
        "status": "created",
        "tx_signature": None,
        "delivered_at": None,
        "delivery_result": None,
        "buyer_secret": str(uuid.uuid4()),
        "used": False,
    }

    create_order_db(order_id, order)

    return {
        "order_id": order_id,
        "buyer_secret":
    order["buyer_secret"],
        "price": seller["price"],
        "seller_id": seller["seller_id"],
        "seller_wallet": payment_wallet_for(seller["seller_wallet"]),
        "actual_agent_wallet": seller["seller_wallet"],
        "payment_target": payment_target(),
        "seller_url": seller.get("url") or "",
        "seller_source": seller.get("source"),
    }


@app.post("/verify-payment")
def verify_payment(req: VerifyPaymentRequest, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}
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

        new_reputation = None

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
    from iat.api.multi_exec import multi_call, select_best_result, compute_consensus
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
def verify_payment_multicall(req: VerifyPaymentRequest, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}
    base = verify_payment(req, x_api_key=x_api_key)
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

    from iat.api.multi_exec import compute_consensus

    consensus = compute_consensus(results)

    if not best:
        return {
            "status": "multicall_failed",
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
           "consensus": consensus,
        }
    if consensus.get("status") != "passed":
        payout_info = {
            "winner_payment_status": "blocked_by_consensus",
            "reason": "consensus_not_reached",
            "consensus": consensus,
        }
    else:
        payout_info = payout_winner_if_escrow(order, best, agents)

    winner_id = best.get("agent_id") if best else None
    if winner_id:
        winner_reputation = update_agent_reputation_db(winner_id, success=True)
        payout_info["winner_new_reputation"] = winner_reputation

    final_result["settlement"] = payout_info
    update_order_delivered_db(req.order_id, req.tx_signature, final_result)

    return final_result

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



@app.get("/transactions")
def transactions():
    orders = list_orders_db()

    txs = []

    for order_id, order in orders.items():
        if order.get("status") != "delivered":
            continue

        delivery = order.get("delivery_result") or {}

        txs.append({
            "order_id": order_id,
            "service": order.get("service"),
            "query": order.get("query"),
            "seller_id": order.get("seller_id"),
            "seller_source": order.get("seller_source"),
            "price_iat": order.get("price"),
            "tx_signature": order.get("tx_signature"),
            "delivered_at": order.get("delivered_at"),
            "protocol_status": delivery.get("status"),
            "agents_called": delivery.get("agents_called"),
            "best_agent": (delivery.get("best") or {}).get("agent_id"),
        })

    return {
        "status": "ok",
        "count": len(txs),
        "transactions": txs[:50],
    }


@app.get("/leaderboard")
def leaderboard():
    orders = list_orders_db()
    agents = list_agents_db()

    stats = {}

    for agent in agents:
        agent_id = agent.get("agent_id")
        stats[agent_id] = {
            "agent_id": agent_id,
            "service": agent.get("service"),
            "reputation": agent.get("reputation"),
            "listed_price_iat": agent.get("price"),
            "wins": 0,
            "paid_orders": 0,
            "revenue_iat": 0,
            "last_active": agent.get("updated_at"),
        }

    for order_id, order in orders.items():
        if order.get("status") != "delivered":
            continue

        seller_id = order.get("seller_id")
        price = float(order.get("price") or 0)
        delivery = order.get("delivery_result") or {}
        best_agent = (delivery.get("best") or {}).get("agent_id")

        if seller_id in stats:
            stats[seller_id]["paid_orders"] += 1
            stats[seller_id]["revenue_iat"] += price

        if best_agent in stats:
            stats[best_agent]["wins"] += 1

    leaderboard_items = list(stats.values())

    for item in leaderboard_items:
        item["revenue_iat"] = round(item["revenue_iat"], 4)

    leaderboard_items.sort(
        key=lambda x: (
            x["wins"],
            x["paid_orders"],
            x["reputation"] or 0,
        ),
        reverse=True,
    )

    return {
        "status": "ok",
        "count": len(leaderboard_items),
        "leaderboard": leaderboard_items,
    }

def require_admin_key(x_api_key: str | None):
    expected = os.getenv("IAT_ADMIN_API_KEY")
    if not expected:
        return True
    return x_api_key == expected


@app.get("/settlements")
def settlements():
    orders = list_orders_db()
    rows = []

    for order_id, order in orders.items():
        if order.get("status") != "delivered":
            continue

        delivery = order.get("delivery_result") or {}
        best = delivery.get("best") or {}
        best_agent = best.get("agent_id")
        seller_id = order.get("seller_id")

        if not best_agent:
            continue

        rows.append({
            "order_id": order_id,
            "service": order.get("service"),
            "query": order.get("query"),
            "tx_signature": order.get("tx_signature"),
            "payer_paid_to": "escrow_wallet" if order.get("seller_wallet") == os.getenv("IAT_ESCROW_WALLET") else seller_id,
            "best_agent": best_agent,
            "price_iat": order.get("price"),
            "winner_payment_status": "payout_due" if order.get("seller_wallet") == os.getenv("IAT_ESCROW_WALLET") else ("already_paid" if best_agent == seller_id else "payout_due"),
            "payout_due_to": best_agent if order.get("seller_wallet") == os.getenv("IAT_ESCROW_WALLET") else (None if best_agent == seller_id else best_agent),
        })

    return {
        "status": "ok",
        "count": len(rows),
        "settlements": rows[:50],
    }


@app.post("/intent-preview")
def intent_preview(payload: dict):
    service = payload.get("service")
    query = payload.get("query")
    max_price = float(payload.get("max_price", 999999))
    priority = payload.get("priority", "quality")

    if not service:
        return {
            "status": "error",
            "message": "missing service",
        }

    agents = get_agents_for_service_db(service)

    bids = []

    for agent in agents:
        price = float(agent.get("price") or 999999)
        reputation = float(agent.get("reputation") or 0.5)

        if price > max_price:
            continue

        estimated_latency = 1.0 + (price / 10)
        confidence = min(0.99, reputation + 0.05)

        price_score = 1 / price if price > 0 else 0
        latency_score = 1 / estimated_latency if estimated_latency > 0 else 0

        if priority == "price":
            score = (
                reputation * 0.25 +
                confidence * 0.20 +
                price_score * 0.40 +
                latency_score * 0.15
            )
        elif priority == "speed":
            score = (
                reputation * 0.25 +
                confidence * 0.20 +
                price_score * 0.15 +
                latency_score * 0.40
            )
        else:
            score = (
                reputation * 0.35 +
                confidence * 0.25 +
                price_score * 0.20 +
                latency_score * 0.20
            )

        bids.append({
            "agent_id": agent.get("agent_id"),
            "service": agent.get("service"),
            "url": agent.get("url"),
            "wallet": agent.get("wallet"),
            "price_iat": price,
            "reputation": reputation,
            "confidence": round(confidence, 4),
            "estimated_latency": round(estimated_latency, 4),
            "score": round(score, 6),
        })

    bids.sort(key=lambda x: x["score"], reverse=True)

    return {
        "status": "ok",
        "type": "intent_preview",
        "intent": {
            "service": service,
            "query": query,
            "max_price": max_price,
            "priority": priority,
        },
        "agents_found": len(agents),
        "bids_count": len(bids),
        "selected": bids[:3],
        "all_bids": bids,
    }



def payout_winner_if_escrow(order, best, agents):
    escrow_wallet = os.getenv("IAT_ESCROW_WALLET")
    escrow_keypair = os.getenv("IAT_ESCROW_KEYPAIR_JSON") or os.getenv("IAT_ESCROW_KEYPAIR_PATH")

    if not escrow_wallet or not escrow_keypair:
        return {
            "winner_payment_status": "payout_due",
            "payout_tx": None,
            "reason": "escrow_not_configured",
        }

    if order.get("seller_wallet") != escrow_wallet:
        return {
            "winner_payment_status": "payout_due",
            "payout_tx": None,
            "reason": "buyer_did_not_pay_escrow",
        }

    best_agent_id = best.get("agent_id") if best else None
    if not best_agent_id:
        return {
            "winner_payment_status": "payout_due",
            "payout_tx": None,
            "reason": "no_best_agent",
        }

    winner = None
    for agent in agents:
        if agent.get("agent_id") == best_agent_id:
            winner = agent
            break

    if not winner:
        return {
            "winner_payment_status": "payout_due",
            "payout_tx": None,
            "reason": "winner_not_found",
        }

    winner_wallet = winner.get("wallet")
    if not winner_wallet:
        return {
            "winner_payment_status": "payout_due",
            "payout_tx": None,
            "reason": "winner_wallet_missing",
        }

    try:
        from iat.transfer import send_iat

        payout_tx = send_iat(
            escrow_keypair,
            winner_wallet,
            float(order.get("price") or 0),
            "payout_" + order.get("order_id")
        )

        return {
            "winner_payment_status": "paid",
            "payout_tx": payout_tx,
            "payout_to_agent": best_agent_id,
            "payout_to_wallet": winner_wallet,
        }

    except Exception as e:
        return {
            "winner_payment_status": "payout_failed",
            "payout_tx": None,
            "reason": str(e),
        }


@app.post("/confirm-delivery")
def confirm_delivery(order_id: str, decision: str, buyer_secret: str):
    order = get_order_db(order_id)

    if not order:
        return {"status": "error", "message": "order not found"}

    if buyer_secret != order.get("buyer_secret"):
        return {"status": "error", "message": "unauthorized"}

    if decision not in ["accept", "reject"]:
        return {"status": "error", "message": "invalid decision"}

    if decision == "accept":
        update_order_db(order_id, {"status": "ready_to_release"})
        return {
            "status": "ok",
            "message": "delivery accepted",
            "order_id": order_id,
            "payout_state": "ready_to_release"
        }

    if decision == "reject":
        update_order_db(order_id, {"status": "disputed"})
        return {
            "status": "ok",
            "message": "order disputed",
            "order_id": order_id,
            "payout_state": "disputed"
        }


@app.post("/release-payout")
def release_payout(order_id: str):
    order = get_order_db(order_id)

    if not order:
        return {"status": "error", "message": "order not found"}

    if order.get("status") == "settled":
        return {"status": "error", "message": "already_settled"}

    if order.get("status") != "ready_to_release":
        return {"status": "error", "message": "order not ready for payout"}

    delivery = order.get("delivery_result") or {}
    best = delivery.get("best") or {}
    best_agent_id = best.get("agent_id")

    if not best_agent_id:
        return {"status": "error", "message": "no best agent"}

    agents = get_agents_for_service_db(order.get("service"))

    winner = None
    for a in agents:
        if a.get("agent_id") == best_agent_id:
            winner = a
            break

    if not winner:
        return {"status": "error", "message": "winner agent not found"}

    escrow_key = os.getenv("IAT_ESCROW_KEYPAIR_JSON") or os.getenv("IAT_ESCROW_KEYPAIR_PATH")

    if not escrow_key:
        return {"status": "error", "message": "escrow not configured"}

    try:
        tx = send_iat(
            escrow_key,
            winner.get("wallet"),
            order.get("price"),
            order_id=order_id
        )

        update_order_db(order_id, {
            "status": "settled",
            "tx_signature": tx
        })

        return {
            "status": "ok",
            "message": "payout executed",
            "tx": tx,
            "paid_to": winner.get("agent_id")
        }

    except Exception as e:
        return {
            "status": "error",
            "message": "payout failed",
            "error": str(e)
        }

