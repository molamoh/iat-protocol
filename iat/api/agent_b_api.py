import os
import time
import uuid
import requests
from fastapi import FastAPI, Header, Request
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
    update_agent_call_stats_db,
    reactivate_agent_db,
    rename_agent_db,
    set_agent_trust_db,
    slash_agent_stake_db,
    update_agent_volume_stats_db,
    recompute_agent_metrics_db,
    compute_dynamic_stake_required_db,
    get_network_economics_db,
    reset_agent_trust_db,
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
    delete_agent_db,
    get_agent_db,
    get_conn,
    release_conn,
    qmark,
    get_agents_for_service_db,
    update_agent_reputation_db,
    get_network_status_db,
    create_factory_agent_db,
    update_order_db,
    list_buyers_db,
    get_buyer_db,
    is_buyer_banned_db,
    ban_buyer_db,
    unban_buyer_db,
    register_buyer_seen_db,
    update_order_buyer_wallet_db,
    create_agent_delegation_db,
    get_agent_delegation_db,
    list_agent_delegations_db,
    list_delegator_positions_db,
    get_agent_delegated_stake_total_db,
)


class AgentTrustUpdate(BaseModel):
    agent_id: str
    trust_tier: str | None = None
    stake_amount: float | None = None
    stake_required: float | None = None
    risk_score: float | None = None



class AgentStakeVerifyRequest(BaseModel):
    agent_id: str
    tx_signature: str
    expected_amount: float = 0


class DelegationRequest(BaseModel):
    delegation_id: str
    agent_id: str
    delegator_wallet: str
    amount: float


app = FastAPI()

def require_admin_key(x_api_key):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")

    if not expected_key:
        return True

    return x_api_key == expected_key



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
    "sellers": [],
    },
}


class RegisterAgentRequest(BaseModel):
    agent_id: str
    service: str
    url: str | None = None
    wallet: str
    agent_type: str = "standard"
    price: float
    reputation: float = 0.8
    available: bool = True
    stake_amount: float = 0
    stake_required: float = 10
    trust_tier: str = "free"


class OrderRequest(BaseModel):
    service: str
    query: str | None = None
    buyer_wallet: str | None = None


class BuyerPreviewRequest(BaseModel):
    buyer_wallet: str
    prompt: str
    max_price: float | None = None


class VerifyPaymentRequest(BaseModel):
    order_id: str
    tx_signature: str


def select_best_seller(service_name):
    dynamic_agents = get_agents_for_service_db(service_name)

    # Production rule:
    # Only dynamic registry agents are valid sellers.
    # No static registry fallback.
    # No factory fallback.
    if not dynamic_agents:
        return None

    best_agent = select_best_agent(dynamic_agents)

    if not best_agent:
        return None

    return {
        "seller_id": best_agent["agent_id"],
        "seller_wallet": best_agent["wallet"],
        "price": best_agent["price"],
        "reputation": best_agent["reputation"],
        "available": best_agent["available"],
        "url": best_agent["url"],
        "source": "dynamic_registry",
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


def refresh_agent_market_gate(agent_id):
    agent = get_agent_db(agent_id)

    if not agent:
        return None

    updated_agent = apply_seller_stake_gate(agent)
    register_agent_db(updated_agent)

    return get_agent_db(agent_id)


def compute_max_order_value(agent):
    stake_amount = float(agent.get("stake_amount", 0) or 0)
    reputation = float(agent.get("reputation", 0.5) or 0.5)

    # Reputation multiplier
    reputation_multiplier = max(0.25, reputation)

    # Global leverage factor
    leverage_factor = 10.0

    max_value = (
        stake_amount
        * reputation_multiplier
        * leverage_factor
    )

    return round(max_value, 6)


def compute_seller_required_stake(agent):
    price = float(agent.get("price", 0) or 0)
    service = agent.get("service", "")

    # Base market rule:
    # sellers must lock collateral proportional to the value they sell.
    minimum_stake = 10.0
    base_ratio = 0.20

    # Higher-risk services can require more collateral.
    service_risk_multiplier = {
        "web_research": 1.0,
        "risk_report": 1.5,
        "trading_signal": 3.0,
        "financial_analysis": 2.5,
    }.get(service, 1.0)

    required = max(
        minimum_stake,
        price * base_ratio * service_risk_multiplier,
    )

    return round(required, 6)


def apply_seller_stake_gate(agent):
    agent_type = agent.get("agent_type", "seller")

    if agent_type == "foundation":
        agent["available"] = True
        agent["stake_required"] = 0
        agent["max_order_value"] = None
        return agent

    stake_amount = float(agent.get("stake_amount", 0) or 0)

    protocol_required = compute_seller_required_stake(agent)
    seller_declared_required = float(agent.get("stake_required", 0) or 0)
    stake_required = max(protocol_required, seller_declared_required)

    agent["stake_required"] = stake_required

    max_order_value = compute_max_order_value(agent)
    agent["max_order_value"] = max_order_value

    price = float(agent.get("price", 0) or 0)

    if stake_amount < stake_required:
        agent["available"] = False
        agent["trust_tier"] = "stake_required"
    elif price > max_order_value:
        agent["available"] = False
        agent["trust_tier"] = "capacity_exceeded"
    else:
        agent["available"] = bool(agent.get("available", True))
        agent["trust_tier"] = agent.get("trust_tier", "staked")

    return agent


@app.post("/register-agent")
def register_agent(req: RegisterAgentRequest):
    agent = req.model_dump()
    agent = apply_seller_stake_gate(agent)
    register_agent_db(agent)

    return {
        "status": "registered",
        "agent": agent,
    }


@app.post("/agent-heartbeat")
def agent_heartbeat(req: RegisterAgentRequest):
    agent = req.model_dump()
    agent = apply_seller_stake_gate(agent)
    register_agent_db(agent)

    return {
        "status": "heartbeat_ok",
        "agent_id": agent["agent_id"],
        "agent_type": agent.get("agent_type"),
        "available": agent.get("available"),
        "stake_required": agent.get("stake_required"),
        "timestamp": int(time.time()),
    }




@app.post("/admin/disable-localhost-agents")
def admin_disable_localhost_agents(x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    import sqlite3
    from iat.api.db import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT agent_id, url
        FROM agents
        WHERE url LIKE 'http://localhost:%'
           OR url LIKE 'http://127.0.0.1:%'
    """)
    rows = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        UPDATE agents
        SET available = 0
        WHERE url LIKE 'http://localhost:%'
           OR url LIKE 'http://127.0.0.1:%'
    """)
    affected = cur.rowcount

    conn.commit()
    conn.close()

    return {
        "status": "ok",
        "disabled_count": affected,
        "disabled_agents": rows,
    }


@app.delete("/admin/delete-agent/{agent_id}")
def admin_delete_agent(agent_id: str, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    try:
        deleted = delete_agent_db(agent_id)
    except Exception as e:
        return {
            "status": "error",
            "agent_id": agent_id,
            "error": str(e),
        }

    if not deleted:
        return {
            "status": "not_found",
            "agent_id": agent_id,
        }

    return {
        "status": "ok",
        "deleted_agent": deleted,
    }



@app.post("/admin/delegate-stake")
def admin_delegate_stake(req: DelegationRequest, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    agent = get_agent_db(req.agent_id)

    if not agent:
        return {
            "status": "not_found",
            "agent_id": req.agent_id,
        }

    if req.amount <= 0:
        return {
            "status": "rejected",
            "reason": "invalid_amount",
        }

    delegation = create_agent_delegation_db({
        "delegation_id": req.delegation_id,
        "agent_id": req.agent_id,
        "delegator_wallet": req.delegator_wallet,
        "amount": req.amount,
        "status": "locked",
    })

    return {
        "status": "ok",
        "message": "delegation_locked",
        "delegation": delegation,
    }


@app.get("/agents/{agent_id}/delegations")
def agent_delegations(agent_id: str):
    return {
        "status": "ok",
        "agent_id": agent_id,
        "delegations": list_agent_delegations_db(agent_id),
    }


@app.get("/delegators/{delegator_wallet}/positions")
def delegator_positions(delegator_wallet: str):
    return {
        "status": "ok",
        "delegator_wallet": delegator_wallet,
        "positions": list_delegator_positions_db(delegator_wallet),
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

        from iat.api.multi_exec import compute_agent_market_score

        market_score = compute_agent_market_score(agent)

        own_stake = float(agent.get("stake_amount", 0) or 0)
        delegated_stake_total = get_agent_delegated_stake_total_db(agent["agent_id"])

        # Delegated stake is useful, but capped to avoid rented trust / cartel abuse.
        effective_delegated_stake = min(
            delegated_stake_total,
            own_stake * 0.40,
        )

        listings.append({
            "agent_id": agent["agent_id"],
            "service": agent["service"],
            "url": agent["url"],
            "wallet": agent["wallet"],
            "price_iat": agent["price"],
            "reputation": agent["reputation"],
            "score": compute_agent_score(agent),
            "market_score": market_score,
            "routing_status": "eligible" if online and market_score > -999 else "not_eligible",
            "trust_tier": agent.get("trust_tier"),
            "stake_status": agent.get("stake_status"),
            "stake_amount": agent.get("stake_amount"),
            "delegated_stake_total": delegated_stake_total,
            "effective_delegated_stake": effective_delegated_stake,
            "delegated_stake_cap_ratio": 0.40,
            "stake_required": agent.get("stake_required"),
            "stake_slashed_total": agent.get("stake_slashed_total"),
            "risk_score": agent.get("risk_score"),
            "status": "online" if online else "offline",
            "source": "dynamic_registry",
            "updated_at": agent["updated_at"],
        })

    listings = sorted(
        listings,
        key=lambda x: (x["service"], x["status"] != "online", -x["market_score"]),
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



@app.get("/network-economics")
def network_economics():
    return {
        "status": "ok",
        "economics": get_network_economics_db(),
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



def detect_buyer_service(prompt: str):
    text = (prompt or "").lower()

    if any(w in text for w in ["hotel", "hôtel", "paris", "voyage", "travel", "restaurant", "meilleur"]):
        return "web_research"

    if any(w in text for w in ["risk", "risque", "audit", "analyse risque"]):
        return "risk_report"

    if any(w in text for w in ["sentiment", "marché", "market", "btc", "crypto"]):
        return "market_sentiment"

    return "web_research"


def describe_buyer_delivery(service: str, prompt: str):
    if service == "web_research":
        return "Une recherche structurée avec sources, comparaison, critères de qualité, liens utiles et recommandation finale."

    if service == "risk_report":
        return "Une analyse de risque structurée avec facteurs principaux, niveau de risque, justification et recommandation synthétique."

    if service == "market_sentiment":
        return "Une synthèse du sentiment de marché avec signaux dominants, biais de foule et conclusion exploitable."

    return "Un résultat structuré adapté à votre demande."



def detect_purchase_type(prompt: str):
    text = (prompt or "").lower()

    if any(w in text for w in ["car", "voiture", "vehicle", "occasion", "used car"]):
        return "used_car_search"

    if any(w in text for w in ["hotel", "hôtel", "travel", "trip", "stay", "paris"]):
        return "hotel_search"

    if any(w in text for w in ["restaurant", "food", "dinner", "lunch"]):
        return "restaurant_search"

    return "general_research"


def extract_basic_requirements(prompt: str):
    text = (prompt or "").lower()
    requirements = {}

    if "paris" in text:
        requirements["location"] = "Paris"
    if "lyon" in text:
        requirements["location"] = "Lyon"

    if "toyota" in text:
        requirements["brand"] = "Toyota"
    if "hybrid" in text or "hybride" in text:
        requirements["fuel"] = "hybrid"
    if "automatic" in text or "automatique" in text:
        requirements["transmission"] = "automatic"

    import re
    amounts = re.findall(r"(\d{3,6})\s?(€|eur|euro|iat)?", text)
    if amounts:
        requirements["budget"] = float(amounts[0][0])

    return requirements


def buyer_missing_requirements(prompt: str, purchase_type: str):
    known = extract_basic_requirements(prompt)

    required_by_type = {
        "used_car_search": [
            "budget",
            "location",
            "fuel",
            "max_mileage",
            "min_year",
            "transmission",
            "usage",
        ],
        "hotel_search": [
            "location",
            "dates",
            "budget",
            "number_of_people",
            "quality_level",
        ],
        "restaurant_search": [
            "location",
            "budget",
            "cuisine",
            "date_or_time",
            "number_of_people",
        ],
        "general_research": [
            "topic",
            "depth",
            "deadline",
        ],
    }

    questions_by_field = {
        "budget": "What is your maximum budget?",
        "location": "Which city or country should we search in?",
        "fuel": "Do you prefer petrol, diesel, hybrid, electric, or no preference?",
        "max_mileage": "What maximum mileage do you accept?",
        "min_year": "What is the minimum year you want?",
        "transmission": "Do you want manual, automatic, or no preference?",
        "usage": "What is the main use: city, family, commuting, business, or long trips?",
        "dates": "What dates do you need?",
        "number_of_people": "How many people is this for?",
        "quality_level": "Do you prefer budget, balanced value, premium, or luxury?",
        "cuisine": "What cuisine or food style do you prefer?",
        "date_or_time": "For what date or time?",
        "topic": "What exact topic should be researched?",
        "depth": "Do you want a quick summary or a deep report?",
        "deadline": "When do you need the result?",
    }

    required = required_by_type.get(purchase_type, [])
    missing = [field for field in required if field not in known]

    return {
        "known_requirements": known,
        "missing_requirements": missing,
        "questions": [questions_by_field[f] for f in missing if f in questions_by_field],
    }


@app.post("/buyer/preview")
def buyer_preview(req: BuyerPreviewRequest):
    if is_buyer_banned_db(req.buyer_wallet):
        return {
            "status": "rejected",
            "message": "Votre wallet n’est pas éligible pour utiliser le service actuellement.",
        }

    purchase_type = detect_purchase_type(req.prompt)
    requirements = buyer_missing_requirements(req.prompt, purchase_type)

    if requirements["missing_requirements"]:
        return {
            "status": "needs_clarification",
            "protocol_language": "en",
            "buyer_summary": {
                "request_understood": req.prompt,
                "detected_purchase_type": purchase_type,
                "known_requirements": requirements["known_requirements"],
                "missing_requirements": requirements["missing_requirements"],
                "questions": requirements["questions"],
                "message": "We need a few more details to recommend the best value-for-money offer.",
            },
        }

    service = detect_buyer_service(req.prompt)
    agents = get_agents_for_service_db(service)

    if req.max_price is not None:
        agents = [
            a for a in agents
            if float(a.get("price", 0) or 0) <= float(req.max_price)
        ]

    available_agents = [
        a for a in agents
        if bool(a.get("available", True))
    ]

    if not available_agents:
        return {
            "status": "no_offer_available",
            "buyer_summary": {
                "request_understood": req.prompt,
                "detected_service": service,
                "reason": "Aucune offre disponible ne respecte actuellement les critères de prix, disponibilité et qualité minimale.",
            },
        }

    from iat.api.multi_exec import compute_agent_market_score

    ranked = sorted(
        available_agents,
        key=lambda a: compute_agent_market_score(a) / max(float(a.get("price", 1) or 1), 0.001),
        reverse=True,
    )

    best = ranked[0]

    prices = [float(a.get("price", 0) or 0) for a in available_agents]

    recommended_price = float(best.get("price", 0) or 0)
    quality_score = round(min(max(float(best.get("reputation", 0.8) or 0.8), 0), 1), 3)
    value_score = round(compute_agent_market_score(best) / max(recommended_price, 0.001), 6)

    return {
        "status": "preview",
        "buyer_summary": {
            "request_understood": req.prompt,
            "detected_service": service,
            "expected_delivery": describe_buyer_delivery(service, req.prompt),
            "recommended_price_iat": recommended_price,
            "min_price_available_iat": min(prices),
            "max_price_available_iat": max(prices),
            "buyer_max_price_iat": req.max_price,
            "estimated_quality": "high" if quality_score >= 0.85 else "medium",
            "quality_score": quality_score,
            "value_for_money": "excellent" if value_score >= 1 else "good",
            "estimated_delivery_time": "quelques secondes après paiement",
        },
        "recommendation": {
            "why_this_offer": "Offre recommandée car elle présente le meilleur équilibre entre prix, qualité attendue, disponibilité et fiabilité.",
            "recommended_action": "Confirmer pour créer l’ordre de paiement.",
        },
        "internal_next_step": {
            "create_order_payload": {
                "service": service,
                "query": req.prompt,
                "buyer_wallet": req.buyer_wallet,
            }
        }
    }


@app.post("/create-order")
def create_order(req: OrderRequest, x_api_key: str | None = Header(default=None)):
    print("ESCROW ENV:", os.getenv("IAT_ESCROW_WALLET"))
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    buyer_wallet = req.buyer_wallet

    if buyer_wallet and is_buyer_banned_db(buyer_wallet):
        return {
            "status": "rejected",
            "reason": "buyer_blacklisted",
            "buyer_wallet": buyer_wallet,
        }

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
        "buyer_wallet": buyer_wallet,
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


@app.post("/verify-payment-base")
def verify_payment(req: VerifyPaymentRequest, x_api_key: str | None = Header(default=None), deliver: bool = True):
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
        buyer_wallet = order.get("buyer_wallet")
        banned_buyer = None

        if buyer_wallet:
            banned_buyer = ban_buyer_db(
                buyer_wallet,
                reason="replay_tx_attempt",
            )

        return {
            "status": "tx_already_processed",
            "buyer_wallet": buyer_wallet,
            "buyer_banned": bool(banned_buyer),
            "ban_reason": "replay_tx_attempt" if banned_buyer else None,
        }

    if not verify_tx_signature(req.tx_signature):
        buyer_wallet = order.get("buyer_wallet")
        banned_buyer = None

        if buyer_wallet:
            banned_buyer = ban_buyer_db(
                buyer_wallet,
                reason="invalid_tx_signature",
            )

        return {
            "status": "invalid_signature",
            "buyer_wallet": buyer_wallet,
            "buyer_banned": bool(banned_buyer),
            "ban_reason": "invalid_tx_signature" if banned_buyer else None,
        }

    tx_details = get_tx_details(req.tx_signature)
    transfer_info = extract_transfer_checked_info(tx_details)
    memo = extract_memo(tx_details)

    buyer_wallet = None
    if transfer_info:
        buyer_wallet = transfer_info.get("authority")

    if buyer_wallet:
        try:
            register_buyer_seen_db(buyer_wallet)
            update_order_buyer_wallet_db(req.order_id, buyer_wallet)
            order["buyer_wallet"] = buyer_wallet
        except Exception as e:
            print("Buyer tracking error:", e)

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
        if not deliver:
            return {
                "status": "paid",
                "service": order["service"],
                "seller_id": order.get("seller_id"),
                "seller_source": order.get("seller_source"),
                "new_reputation": None,
                "data": None,
            }

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
    from iat.api.multi_exec import multi_call, select_best_result, select_top_agents, select_top_agents, compute_consensus
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
        "agents_called": len(selected_agents),
        "selected_agents": [a.get("agent_id") for a in selected_agents],
        "results": results,
        "best": best
    }



def force_agent_into_selection(selected_agents, all_agents, forced_agent_id, limit=3):
    if not forced_agent_id:
        return selected_agents

    forced = None
    for agent in all_agents:
        if agent.get("agent_id") == forced_agent_id:
            forced = agent
            break

    if not forced:
        return selected_agents

    # Remove duplicate if already present
    selected_agents = [
        a for a in selected_agents
        if a.get("agent_id") != forced_agent_id
    ]

    # Put forced agent first for debug, then keep limit
    return [forced] + selected_agents[: max(0, limit - 1)]



def execute_onchain_slash(agent_id, amount, order_id):
    treasury_wallet = os.getenv("IAT_SLASH_TREASURY_WALLET")
    escrow_key = os.getenv("IAT_ESCROW_KEYPAIR_JSON") or os.getenv("IAT_ESCROW_KEYPAIR_PATH")

    if not treasury_wallet:
        return {
            "status": "skipped",
            "reason": "slash_treasury_not_configured",
        }

    if not escrow_key:
        return {
            "status": "skipped",
            "reason": "escrow_key_not_configured",
        }

    if not amount or float(amount) <= 0:
        return {
            "status": "skipped",
            "reason": "no_amount_to_slash",
        }

    try:
        tx = send_iat(
            escrow_key,
            treasury_wallet,
            float(amount),
            memo_text=f"SLASH:{agent_id}:{order_id}",
        )

        return {
            "status": "sent",
            "tx_signature": tx,
            "to": treasury_wallet,
            "amount": float(amount),
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


@app.post("/verify-payment-multicall")
@app.post("/verify-payment")
def verify_payment_multicall(req: VerifyPaymentRequest, x_api_key: str | None = Header(default=None)):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}
    base = verify_payment(req, x_api_key=x_api_key, deliver=False)
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

    from iat.api.multi_exec import multi_call, select_best_result, select_top_agents

    paid_order = dict(order)
    paid_order["tx_signature"] = req.tx_signature

    selected_agents = select_top_agents(agents, limit=3)

    # DEBUG ONLY: force one agent into execution when env var is set.
    # Example on Render env:
    # IAT_FORCE_AGENT_ID=web_agent_malicious
    # FORCE_AGENT disabled in production
    forced_agent_id = None
    selected_agents = force_agent_into_selection(
        selected_agents,
        agents,
        forced_agent_id,
        limit=3,
    )

    results = multi_call(selected_agents, paid_order)
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
        "agents_called": len(selected_agents),
        "payment_result": base,
        "results": results,
        "best": best,
        "consensus": consensus,
    }

# --- SLASH suspicious agents ---
    suspicious = consensus.get("suspicious_agents", [])

    # Prevent double slashing same agent in same order
    suspicious = list(dict.fromkeys(suspicious))

    slashing_events = []
    economic_volume_updates = []
    order_value = float(order.get("price", 0) or 0)

    # Honest/fraud value accounting
    for r in results:
        aid = r.get("agent_id")
        if not aid:
            continue

        if aid in suspicious:
            econ = update_agent_volume_stats_db(aid, order_value, honest=False)
            if econ:
                economic_volume_updates.append(econ)
        elif r.get("success"):
            econ = update_agent_volume_stats_db(aid, order_value, honest=True)
            if econ:
                economic_volume_updates.append(econ)

    for agent_id in suspicious:
        update_agent_reputation_db(agent_id, success=False)

        try:
            slash_info = slash_agent_stake_db(
                agent_id,
                slash_ratio=0.10,
                reason="consensus_suspicious_agent",
            )
            if slash_info:
                refreshed_agent = refresh_agent_market_gate(agent_id)

                onchain = execute_onchain_slash(
                    agent_id,
                    slash_info.get("slashed_amount", 0),
                    req.order_id,
                )
                slash_info["onchain_slash"] = onchain
                slash_info["agent_after_slash"] = refreshed_agent
                slashing_events.append(slash_info)
        except Exception as e:
            print("Stake slashing error:", e)

# --- payout logic ---
    winner_id = best.get("agent_id") if best else None
    winner_score = float(best.get("selection_score", 0) or 0) if best else 0
    winner_details = best.get("selection_score_details", {}) if best else {}
    winner_is_suspicious = winner_id in suspicious if winner_id else True

    consensus_passed = consensus.get("status") == "passed"

    # Weak pass rule:
    # If consensus is globally suspicious but the selected winner has a strong
    # final score and is not individually suspicious, allow payout.
    weak_pass = (
        not consensus_passed
        and best is not None
        and not winner_is_suspicious
        and winner_score >= 0.75
    )

    if not consensus_passed and not weak_pass:
        payout_info = {
            "winner_payment_status": "blocked_by_consensus",
            "reason": "consensus_not_reached",
            "consensus": consensus,
            "winner_id": winner_id,
            "winner_selection_score": winner_score,
            "winner_score_details": winner_details,
            "slashed_agents": suspicious,
            "stake_slashing_events": slashing_events,
        }

    elif weak_pass:
        payout_info = {
            "winner_payment_status": "payout_due_weak_consensus",
            "reason": "weak_consensus_manual_review",
            "consensus": consensus,
            "winner_id": winner_id,
            "winner_selection_score": winner_score,
            "winner_score_details": winner_details,
            "slashed_agents": suspicious,
            "stake_slashing_events": slashing_events,
            "consensus_status": consensus.get("status"),
            "weak_pass": True,
        }

    else:
        payout_info = payout_winner_if_escrow(order, best, agents)

        payout_info["slashed_agents"] = suspicious
        payout_info["stake_slashing_events"] = slashing_events
        payout_info["consensus_status"] = consensus.get("status")
        payout_info["weak_pass"] = False
        payout_info["winner_selection_score"] = winner_score
        payout_info["winner_score_details"] = winner_details

        winner_reputation = None
        if winner_id:
            winner_reputation = update_agent_reputation_db(winner_id, success=True)
        payout_info["winner_new_reputation"] = winner_reputation
    
    final_result["economic_volume_updates"] = economic_volume_updates
    final_result["settlement"] = payout_info

    # --- recompute dynamic metrics ---
    recomputed_agents = []

    processed_agent_ids = set()

    for r in results:
        aid = r.get("agent_id")

        if not aid or aid in processed_agent_ids:
            continue

        processed_agent_ids.add(aid)

        try:
            metrics = recompute_agent_metrics_db(aid)

            if metrics:
                recomputed_agents.append(metrics)

        except Exception as e:
            print("Recompute metrics error:", e)

    final_result["recomputed_agents"] = recomputed_agents

    # --- LEARNING LAYER (call + win stats) ---
    agent_ids = [a.get("agent_id") for a in selected_agents]
    winner_id = best.get("agent_id") if best else None

    latencies = {
        r.get("agent_id"): r.get("latency", 0)
        for r in results
        if r.get("agent_id")
    }

    try:
        update_agent_call_stats_db(agent_ids, winner_id, latencies=latencies)
    except Exception as e:
        print("Learning layer error:", e)

    try:
        save_processed_tx_db(req.tx_signature)
    except Exception as e:
        print("Processed tx save error:", e)

    update_order_delivered_db(req.order_id, req.tx_signature, final_result)

    return final_result






@app.post("/admin/test-onchain-slash-agent/{agent_id}")
def admin_test_onchain_slash_agent(agent_id: str, request: Request, amount: float = 0.1):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    onchain = execute_onchain_slash(
        agent_id,
        amount,
        order_id="ADMIN_TEST",
    )

    return {
        "status": "ok",
        "agent_id": agent_id,
        "amount": amount,
        "onchain_slash": onchain,
    }


@app.post("/admin/test-slash-agent/{agent_id}")
def admin_test_slash_agent(agent_id: str, request: Request, slash_ratio: float = 0.10):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    result = slash_agent_stake_db(
        agent_id,
        slash_ratio=slash_ratio,
        reason="admin_test_slash",
    )

    refreshed_agent = refresh_agent_market_gate(agent_id)

    if not result:
        return {
            "status": "error",
            "message": "agent_not_found",
            "agent_id": agent_id,
        }

    return {
        "status": "ok",
        "slash": result,
        "agent_after_slash": refreshed_agent,
    }




@app.post("/admin/test-lock-agent-stake/{agent_id}")
def admin_test_lock_agent_stake(
    agent_id: str,
    amount: float = 100,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    agent = get_agent_db(agent_id)

    if not agent:
        return {
            "status": "not_found",
            "agent_id": agent_id,
        }

    conn = get_conn()
    cur = conn.cursor()
    pmark = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE agents
    SET stake_status = 'locked',
        stake_amount = {pmark},
        stake_locked_at = {pmark},
        stake_unlock_requested_at = NULL,
        updated_at = {pmark}
    WHERE agent_id = {pmark}
    """, (
        amount,
        now,
        now,
        agent_id,
    ))

    conn.commit()
    release_conn(conn)

    updated = get_agent_db(agent_id)

    return {
        "status": "ok",
        "message": "test_stake_locked",
        "agent": updated,
    }


@app.post("/admin/request-agent-unstake/{agent_id}")
def admin_request_agent_unstake(
    agent_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    agent = get_agent_db(agent_id)

    if not agent:
        return {
            "status": "not_found",
            "agent_id": agent_id,
        }

    if agent.get("stake_status") != "locked":
        return {
            "status": "rejected",
            "reason": "stake_not_locked",
            "agent_id": agent_id,
            "stake_status": agent.get("stake_status"),
        }

    conn = get_conn()
    cur = conn.cursor()
    pmark = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE agents
    SET stake_status = 'unlock_requested',
        stake_unlock_requested_at = {pmark},
        available = 0,
        updated_at = {pmark}
    WHERE agent_id = {pmark}
    """, (
        now,
        now,
        agent_id,
    ))

    conn.commit()
    release_conn(conn)

    updated = get_agent_db(agent_id)

    return {
        "status": "ok",
        "message": "unstake_requested",
        "agent_id": agent_id,
        "cooldown_seconds": 86400,
        "agent": updated,
    }



@app.post("/admin/execute-agent-unstake/{agent_id}")
def admin_execute_agent_unstake(
    agent_id: str,
    x_api_key: str | None = Header(default=None),
):
    if not require_admin_key(x_api_key):
        return {"status": "error", "message": "unauthorized"}

    cooldown_seconds = 86400

    agent = get_agent_db(agent_id)

    if not agent:
        return {
            "status": "not_found",
            "agent_id": agent_id,
        }

    if agent.get("stake_status") != "unlock_requested":
        return {
            "status": "rejected",
            "reason": "unlock_not_requested",
            "stake_status": agent.get("stake_status"),
        }

    requested_at = int(agent.get("stake_unlock_requested_at") or 0)
    now = int(time.time())

    remaining = cooldown_seconds - (now - requested_at)

    if remaining > 0:
        return {
            "status": "cooldown_active",
            "remaining_seconds": remaining,
            "agent_id": agent_id,
        }

    conn = get_conn()
    cur = conn.cursor()
    pmark = qmark()

    cur.execute(f"""
    UPDATE agents
    SET stake_status = 'unstaked',
        stake_amount = 0,
        available = 0,
        updated_at = {pmark}
    WHERE agent_id = {pmark}
    """, (
        now,
        agent_id,
    ))

    conn.commit()
    release_conn(conn)

    updated = get_agent_db(agent_id)

    return {
        "status": "ok",
        "message": "unstake_executed",
        "agent": updated,
    }


@app.post("/admin/verify-agent-stake")
def admin_verify_agent_stake(req: AgentStakeVerifyRequest, request: Request):
    expected_key = os.getenv("IAT_ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if expected_key and provided_key != expected_key:
        return {
            "status": "error",
            "message": "unauthorized",
        }

    escrow_wallet = os.getenv("IAT_ESCROW_WALLET")

    if not escrow_wallet:
        return {
            "status": "error",
            "message": "escrow_wallet_not_configured",
        }

    tx_details = get_tx_details(req.tx_signature)

    if not tx_details:
        return {
            "status": "error",
            "message": "tx_not_found",
        }

    transfer = extract_transfer_checked_info(tx_details)
    memo = extract_memo(tx_details)

    if not transfer:
        return {
            "status": "error",
            "message": "transfer_not_found",
        }

    expected_ata = str(
        get_associated_token_address(
            Pubkey.from_string(escrow_wallet),
            Pubkey.from_string(IAT_MINT),
        )
    )

    actual_destination = transfer.get("destination")
    actual_mint = transfer.get("mint")
    actual_amount = float(transfer.get("ui_amount") or 0)

    memo_ok = memo is not None and f"STAKE:{req.agent_id}" in str(memo)
    receiver_ok = actual_destination == expected_ata
    mint_ok = actual_mint == IAT_MINT
    amount_ok = actual_amount >= float(req.expected_amount or 0)

    checks = {
        "receiver_ok": receiver_ok,
        "mint_ok": mint_ok,
        "amount_ok": amount_ok,
        "memo_ok": memo_ok,
        "expected_ata": expected_ata,
        "actual_destination": actual_destination,
        "expected_mint": IAT_MINT,
        "actual_mint": actual_mint,
        "expected_amount": req.expected_amount,
        "actual_amount": actual_amount,
        "expected_memo": f"STAKE:{req.agent_id}",
        "actual_memo": str(memo),
    }

    if not (receiver_ok and mint_ok and amount_ok and memo_ok):
        return {
            "status": "invalid_stake",
            "checks": checks,
        }

    # Tier by amount
    if actual_amount >= 1000:
        trust_tier = "premium"
    elif actual_amount >= 100:
        trust_tier = "standard"
    elif actual_amount >= 10:
        trust_tier = "recovery"
    else:
        trust_tier = "free"

