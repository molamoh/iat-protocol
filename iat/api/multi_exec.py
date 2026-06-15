

FOUNDATION_AGENT_CAPABILITIES = {
    "foundation_web_standard": {
        "role": "web_research",
        "specialty": "general_web_research",
        "engine": "foundation_web_research",
    },
    "foundation_web_cheap": {
        "role": "web_research",
        "specialty": "fast_low_cost_research",
        "engine": "foundation_web_research",
    },
    "foundation_product_agent": {
        "role": "product_ranking",
        "specialty": "product_comparison",
        "engine": "foundation_product_ranking",
    },
    "buyer_foundation_web_research": {
        "role": "web_research",
        "specialty": "buyer_fallback_research",
        "engine": "foundation_web_research",
    },
}


def get_foundation_agent_profile(agent):
    agent_id = str(agent.get("agent_id", "") or "")
    mapped = FOUNDATION_AGENT_CAPABILITIES.get(agent_id)
    if mapped:
        return mapped

    foundation_role = str(agent.get("foundation_role") or "").lower()

    if foundation_role == "research":
        return {
            "role": "web_research",
            "specialty": "foundation_research",
            "engine": "foundation_web_research",
        }

    if foundation_role == "verification":
        return {
            "role": "verification",
            "specialty": "foundation_verification",
            "engine": "foundation_web_research",
        }

    return {
        "role": agent.get("service", "foundation"),
        "specialty": "generic_foundation_execution",
        "engine": "foundation_generic",
    }


import time
import os
import json
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed



def parse_json_dict(value):
    if isinstance(value, dict):
        return value

    if not value:
        return {}

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def parse_json_list(value):
    import json

    if isinstance(value, list):
        return value

    if not value:
        return []

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def infer_required_capabilities(order):
    intent = order.get("buyer_intent") or {}

    groq_capabilities = intent.get("required_capabilities") or []

    if isinstance(groq_capabilities, list) and groq_capabilities:
        required = set(str(c).strip() for c in groq_capabilities if str(c).strip())

        # Generic baseline for most buyer-facing autonomous tasks.
        required.add("buyer_research")

        # If the buyer asks for research/analysis and Groq did not include web_search,
        # add it as a generic execution capability, not a vertical hardcode.
        output_mode = str(intent.get("output_mode", "") or "").lower()
        purchase_type = str(intent.get("purchase_type", "") or "").lower()
        goal = str(intent.get("goal", "") or "").lower()
        query = str(order.get("query", "") or "").lower()
        text = " ".join([output_mode, purchase_type, goal, query])

        if any(w in text for w in ["research", "analysis", "current", "latest", "today", "find", "compare"]):
            required.add("web_search")

        return list(required)

    purchase_type = str(intent.get("purchase_type", "") or "").lower()
    goal = str(intent.get("goal", "") or "").lower()
    query = str(order.get("query", "") or "").lower()

    text = " ".join([purchase_type, goal, query])

    required = {"web_search", "buyer_research"}

    if any(w in text for w in ["product", "smartphone", "phone", "laptop", "car", "vehicle", "buy", "price"]):
        required.add("product_research")
        required.add("price_comparison")

    if any(w in text for w in ["travel", "hotel", "trip", "flight", "tourism", "stay"]):
        required.add("travel_research")

    if any(w in text for w in ["finance", "market", "crypto", "btc", "risk", "trading"]):
        required.add("market_research")
        required.add("risk_analysis")

    if any(w in text for w in ["compare", "comparison", "best value", "quality price", "value-for-money"]):
        required.add("price_comparison")

    return list(required)


def compute_specialty_match_score(agent, order):
    """
    Generic specialty routing.

    IAT must not hardcode vertical business routing.
    The buyer request is compared against the agent's declared specialties
    using normalized tokens and lightweight synonym expansion.
    """
    specialties = set(parse_json_list(agent.get("specialties")))

    intent = order.get("buyer_intent") or {}
    requirements = order.get("requirements") or {}

    text = " ".join([
        str(intent.get("purchase_type", "")),
        str(intent.get("goal", "")),
        str(order.get("query", "")),
        " ".join(str(v) for v in requirements.values()),
    ]).lower()

    normalized_text = (
        text.replace("_", " ")
            .replace("-", " ")
            .replace(",", " ")
            .replace(".", " ")
            .replace("/", " ")
    )

    tokens = set(normalized_text.split())

    specialty_aliases = {
        "general_web": ["research", "information", "web", "search", "general"],
        "deep_research": ["deep", "detailed", "complete", "full", "analysis", "research"],
        "fast_research": ["quick", "fast", "summary", "brief"],
        "budget_execution": ["cheap", "low", "budget", "affordable"],
        "market_analysis": ["market", "analysis", "liquidity", "sentiment", "trend"],
        "premium_analysis": ["deep", "premium", "advanced", "detailed", "professional"],
        "risk": ["risk", "evaluation", "audit", "exposure", "danger"],
        "finance": ["finance", "financial", "asset", "investment"],
        "crypto": ["crypto", "btc", "bitcoin", "blockchain"],
        "bitcoin": ["btc", "bitcoin"],
        "market_sentiment": ["sentiment", "crowd", "market", "bias"],
        "consumer_products": ["product", "phone", "smartphone", "laptop", "buy"],
        "shopping_research": ["shopping", "buy", "purchase", "compare"],
        "price_comparison": ["price", "budget", "compare", "comparison"],
        "travel": ["travel", "trip", "flight", "tourism"],
        "hotels": ["hotel", "hotels", "stay"],
        "tourism": ["tourism", "visit", "vacation"],
    }

    score = 0.0

    groq_preferred = intent.get("preferred_specialties") or []

    if isinstance(groq_preferred, list) and groq_preferred:
        preferred = set(str(s).strip().lower() for s in groq_preferred if str(s).strip())
        direct_overlap = specialties.intersection(preferred)

        if direct_overlap:
            score += len(direct_overlap) / max(len(preferred), 1)

        # Also allow alias-level matching between Groq specialties and registered specialties.
        for specialty in specialties:
            alias_tokens = set(specialty_aliases.get(specialty, []))
            specialty_tokens = set(str(specialty).lower().replace("_", " ").split())
            match_tokens = alias_tokens.union(specialty_tokens)

            for preferred_item in preferred:
                preferred_tokens = set(preferred_item.replace("_", " ").split())
                if preferred_tokens.intersection(match_tokens):
                    score += 0.15

    for specialty in specialties:
        specialty_tokens = set(str(specialty).lower().replace("_", " ").split())
        alias_tokens = set(specialty_aliases.get(specialty, []))
        match_tokens = specialty_tokens.union(alias_tokens)

        if tokens.intersection(match_tokens):
            score += 0.5 / max(len(specialties), 1)

    if "general_web" in specialties:
        score += 0.03

    return round(min(score, 1.0), 6)


def compute_capability_match_score(agent, order):
    capabilities = set(parse_json_list(agent.get("capabilities")))
    specialties = set(parse_json_list(agent.get("specialties")))
    required = set(infer_required_capabilities(order))

    if not required:
        return 0.5

    capability_overlap = len(capabilities.intersection(required)) / len(required)

    specialty_bonus = 0
    intent = order.get("buyer_intent") or {}
    text = " ".join([
        str(intent.get("purchase_type", "")),
        str(intent.get("goal", "")),
        str(order.get("query", "")),
    ]).lower()

    if "product" in text or "phone" in text or "smartphone" in text or "laptop" in text:
        if "consumer_products" in specialties or "shopping_research" in specialties:
            specialty_bonus = 0.20

    return round(min(1.0, capability_overlap + specialty_bonus), 6)


def compute_agent_trust_score(agent):
    """
    Generic trust score for buyer-side routing.

    This prepares the future seller economy:
    - reputation
    - success/failure history
    - stake
    - slashing history
    - risk score
    - trust tier

    Returns 0.0 to 1.0.
    """
    reputation = float(agent.get("reputation", 0.5) or 0.5)
    successes = int(agent.get("success_count", 0) or 0)
    failures = int(agent.get("failure_count", 0) or 0)
    stake_amount = float(agent.get("stake_amount", 0) or 0)
    stake_required = float(agent.get("stake_required", 0) or 0)
    dynamic_stake_required = float(agent.get("dynamic_stake_required", 0) or 0)
    risk_score = float(agent.get("risk_score", 0) or 0)
    stake_slashed_total = float(agent.get("stake_slashed_total", 0) or 0)
    trust_tier = str(agent.get("trust_tier", "free") or "free").lower()
    agent_type = str(agent.get("agent_type", "standard") or "standard").lower()

    score = reputation * 0.45

    total_results = successes + failures
    if total_results > 0:
        success_rate = successes / max(total_results, 1)
        score += success_rate * 0.20
    else:
        score += 0.10

    tier_bonus = {
        "premium": 0.15,
        "standard": 0.10,
        "staked": 0.08,
        "free": 0.03,
        "recovery": -0.05,
        "stake_required": -0.15,
        "capacity_exceeded": -0.10,
    }.get(trust_tier, 0.0)

    score += tier_bonus

    if agent_type == "foundation":
        score += 0.12

    effective_required = max(stake_required, dynamic_stake_required)

    if effective_required > 0:
        stake_ratio = min(stake_amount / effective_required, 1.0)
        score += stake_ratio * 0.12
    elif stake_amount > 0:
        score += min(stake_amount / 1000, 1.0) * 0.08

    score -= min(max(risk_score, 0), 1) * 0.25

    if stake_slashed_total > 0:
        slash_penalty = min(stake_slashed_total / (stake_amount + stake_slashed_total + 0.001), 1.0)
        score -= slash_penalty * 0.25

    return round(min(max(score, 0.0), 1.0), 6)


def compute_agent_market_score(agent):
    """
    Market pre-selection score.
    Same wallet is NOT penalized here.
    We rank agents by reliability, history, price, and availability.
    """
    if not bool(agent.get("available", True)):
        return -999999

    reputation = float(agent.get("reputation", 0.5) or 0.5)
    price = float(agent.get("price", 1.0) or 1.0)

    agent_type = agent.get("agent_type", "seller")

    # Foundation agents are protocol infrastructure.
    # They are not market sellers and should bypass
    # seller-market economic penalties.
    if agent_type == "foundation":
        return round(
            1000
            + reputation * 10
            - price * 0.01,
            6
        )
    successes = int(agent.get("success_count", 0) or 0)
    failures = int(agent.get("failure_count", 0) or 0)
    call_count = int(agent.get("call_count", 0) or 0)
    win_count = int(agent.get("win_count", 0) or 0)
    latency_total = float(agent.get("latency_total", 0) or 0)
    stake_amount = float(agent.get("stake_amount", 0) or 0)
    stake_required = float(agent.get("stake_required", 0) or 0)
    risk_score = float(agent.get("risk_score", 0) or 0)
    volume_total = float(agent.get("volume_total", 0) or 0)
    honest_volume = float(agent.get("honest_volume", 0) or 0)
    fraud_volume = float(agent.get("fraud_volume", 0) or 0)
    dynamic_stake_required = float(agent.get("dynamic_stake_required", 0) or 0)
    stake_slashed_total = float(agent.get("stake_slashed_total", 0) or 0)
    trust_tier = agent.get("trust_tier", "free")
    stake_status = agent.get("stake_status", "unstaked")

    avg_latency = (latency_total / call_count) if call_count > 0 else None

    # Anti-gaming:
    # Win rate only becomes meaningful after enough calls.
    raw_win_rate = (win_count / call_count) if call_count > 0 else 0

    confidence = min(call_count / 10, 1.0)
    adjusted_win_rate = raw_win_rate * confidence

    success_bonus = min(successes * 0.03, 0.30)
    failure_penalty = failures * 0.25
    win_rate_bonus = adjusted_win_rate * 0.35

    price_score = 1 / (price + 0.001)

    # Stability: reward low average latency over time.
    stability_bonus = 0
    if avg_latency is not None:
        stability_bonus = min(1 / (avg_latency + 0.1), 1.0) * 0.15

    # Hybrid trust: stake gives a small boost, risk gives a strong penalty.
    trust_bonus = 0
    if stake_amount >= 1000:
        trust_bonus = 0.20
    elif stake_amount >= 100:
        trust_bonus = 0.10
    elif stake_amount >= 10:
        trust_bonus = 0.03

    stake_gap_penalty = 0
    effective_required = max(stake_required, dynamic_stake_required)
    if effective_required > 0 and stake_amount < effective_required:
        stake_gap_penalty = min(0.50, (effective_required - stake_amount) / (effective_required + 0.001) * 0.50)

    # Reward proven honest value; punish fraud value.
    fraud_rate = fraud_volume / volume_total if volume_total > 0 else 0
    honest_rate = honest_volume / volume_total if volume_total > 0 else 0
    adaptive_market_bonus = min(honest_rate * 0.10, 0.10)
    adaptive_fraud_penalty = min(fraud_rate * 0.60, 0.60)

    # Penalize agents with previous slashing history.
    slash_penalty = 0
    if stake_amount > 0:
        slash_penalty = min(stake_slashed_total / (stake_amount + stake_slashed_total + 0.001), 1.0) * 0.40
    elif stake_slashed_total > 0:
        slash_penalty = 0.40

    # Trust tier influences routing, but cannot overpower fraud/stake penalties.
    trust_tier_bonus = {
        "premium": 0.20,
        "standard": 0.10,
        "staked": 0.08,
        "recovery": -0.05,
        "stake_required": -0.50,
        "capacity_exceeded": -0.50,
        "free": 0.0,
    }.get(trust_tier, 0.0)

    # Agents trying to unstake should not be preferred.
    stake_status_penalty = 0
    if stake_status == "unlock_requested":
        stake_status_penalty = 0.75
    elif stake_status == "unstaked" and agent_type != "foundation":
        stake_status_penalty = 0.10

    score = (
        reputation * 1.5
        + success_bonus
        + win_rate_bonus
        + stability_bonus
        + trust_bonus
        + adaptive_market_bonus
        + price_score * 0.25
        - failure_penalty
        - min(risk_score, 1.0) * 0.50
        + trust_tier_bonus
        - stake_gap_penalty
        - adaptive_fraud_penalty
        - slash_penalty
        - stake_status_penalty
    )

    # Runtime adaptive policy enforcement.
    # Policies must create economic friction, not blind destruction.
    try:
        from iat.api.db import get_active_adaptive_policy_db

        policy = get_active_adaptive_policy_db(
            scope="service",
            service=agent.get("service"),
        ) or get_active_adaptive_policy_db(
            scope="protocol",
            service="global",
        )

        if policy:
            exposure_multiplier = float(policy.get("exposure_multiplier", 1.0) or 1.0)
            consensus_multiplier = float(policy.get("consensus_multiplier", 1.0) or 1.0)
            min_stake_multiplier = float(policy.get("min_stake_multiplier", 1.0) or 1.0)

            exposure_multiplier = max(0.10, min(exposure_multiplier, 1.50))
            consensus_multiplier = max(1.00, min(consensus_multiplier, 3.00))
            min_stake_multiplier = max(1.00, min(min_stake_multiplier, 5.00))

            # Higher protocol risk reduces seller market exposure.
            score *= exposure_multiplier

            # When consensus is hardened, risky agents lose routing pressure.
            score -= min(risk_score, 1.0) * (consensus_multiplier - 1.0) * 0.35

            # When stake policy hardens, under-staked agents lose score.
            if effective_required > 0 and stake_amount < effective_required * min_stake_multiplier:
                score -= min(0.50, (min_stake_multiplier - 1.0) * 0.12)

    except Exception:
        # Adaptive policy must never break routing.
        pass

    return round(score, 6)


def compute_buyer_agent_score(agent, order=None):
    """
    Centralized buyer-side routing score.

    Used by:
    - buyer preview
    - buyer run-test
    - create-order
    - future payment/execution pipeline

    This keeps routing consistent across the protocol.
    """
    order = order or {}
    intent = order.get("buyer_intent") or {}

    strategy = str(intent.get("execution_strategy") or "balanced").lower()
    trust_preference = str(intent.get("trust_preference") or "foundation_allowed").lower()
    consensus_preference = str(intent.get("consensus_preference") or "standard").lower()

    # Strict consensus requests require consensus-oriented routing.
    if consensus_preference == "strict":
        strategy = "consensus_required"

    if trust_preference == "foundation_only" and agent.get("agent_type") != "foundation":
        return -999999

    capability = compute_capability_match_score(agent, order)
    specialty = compute_specialty_match_score(agent, order)
    market = compute_agent_market_score(agent)
    trust = compute_agent_trust_score(agent)

    try:
        from iat.api.db import compute_agent_topic_score_db
        routing_topics = extract_topics_from_result(
            {"data": {
                "entities": [],
                "claims": [],
                "structured_signals": {},
                "metrics": {},
            }},
            order,
        )
        topic_score = compute_agent_topic_score_db(
            agent.get("agent_id"),
            routing_topics,
        )
    except Exception:
        topic_score = 0.5

    price = max(float(agent.get("price", 1) or 1), 0.001)
    price_score = 1 / price

    call_count = int(agent.get("call_count", 0) or 0)
    latency_total = float(agent.get("latency_total", 0) or 0)
    avg_latency = latency_total / call_count if call_count > 0 else 1.0
    latency_score = min(1.0, 1 / max(avg_latency, 0.001))

    market_score = market / 1000 if market > 0 else 0

    premium_bonus = 0.0

    preferred_specialties = set(
        str(s).lower()
        for s in (intent.get("preferred_specialties") or [])
    )

    agent_specialties = set(
        str(s).lower()
        for s in parse_json_list(agent.get("specialties"))
    )

    if strategy in ["premium", "safest", "consensus_required"]:
        overlap = preferred_specialties.intersection(agent_specialties)

        if overlap:
            premium_bonus += min(len(overlap) * 0.12, 0.30)

        if "premium_analysis" in agent_specialties:
            premium_bonus += 0.15

        if "risk" in agent_specialties:
            premium_bonus += 0.10

        if "crypto" in agent_specialties:
            premium_bonus += 0.08

        if {"premium_analysis", "risk", "crypto"}.issubset(agent_specialties):
            premium_bonus += 0.08

    if strategy == "cheapest":
        return round(
            capability * 0.30 +
            specialty * 0.20 +
            price_score * 0.35 +
            trust * 0.10 +
            topic_score * 0.10 +
            market_score * 0.05,
            6,
        )

    if strategy in ["premium", "safest"]:
        return round(
            capability * 0.30 +
            specialty * 0.25 +
            trust * 0.35 +
            topic_score * 0.05 +
            market_score * 0.10 +
            premium_bonus +
            price_score * 0.01,
            6,
        )

    if strategy == "fastest":
        return round(
            capability * 0.30 +
            specialty * 0.20 +
            latency_score * 0.25 +
            trust * 0.10 +
            topic_score * 0.10 +
            price_score * 0.10,
            6,
        )

    if strategy == "consensus_required":
        return round(
            capability * 0.35 +
            specialty * 0.25 +
            trust * 0.25 +
            topic_score * 0.05 +
            market_score * 0.17 +
            premium_bonus +
            price_score * 0.01,
            6,
        )

    return round(
        capability * 0.35 +
        specialty * 0.25 +
        trust * 0.18 +
        topic_score * 0.07 +
        price_score * 0.10 +
        market_score * 0.15,
        6,
    )


def compute_required_agent_count(order=None):
    """
    Decide how many agents should participate in execution.

    Future use:
    - consensus security
    - anti-fraud
    - high-value orders
    - premium verification
    - decentralized arbitration
    """
    order = order or {}
    intent = order.get("buyer_intent") or {}

    strategy = str(intent.get("execution_strategy") or "balanced").lower()
    consensus = str(intent.get("consensus_preference") or "standard").lower()
    quality = str(intent.get("quality_preference") or "balanced").lower()
    urgency = str(intent.get("urgency") or "normal").lower()

    if strategy == "fastest":
        return 1

    if consensus == "none":
        return 1

    if consensus == "strict":
        return 5

    if strategy == "consensus_required":
        return 5

    if strategy in ["premium", "safest"]:
        return 4

    if quality in ["premium", "high"]:
        return 4

    if urgency == "high":
        return 2

    return 3





def compute_cluster_diversity_penalty(candidate, already_selected):
    """
    Internal IAT routing firewall.

    Buyers never contact sellers directly.
    This protects protocol/foundation execution from:
    - same-seller domination
    - sybil clusters
    - coordinated consensus manipulation
    """

    candidate_wallet = str(candidate.get("seller_wallet") or candidate.get("wallet") or "")
    candidate_seller = str(candidate.get("seller_id") or "")
    candidate_cluster = str(candidate.get("cluster_id") or "")

    penalty = 0.0

    for existing in already_selected:
        existing_wallet = str(existing.get("seller_wallet") or existing.get("wallet") or "")
        existing_seller = str(existing.get("seller_id") or "")
        existing_cluster = str(existing.get("cluster_id") or "")

        if candidate_seller and existing_seller and candidate_seller == existing_seller:
            penalty += 0.60

        if candidate_wallet and existing_wallet and candidate_wallet == existing_wallet:
            penalty += 0.80

        if candidate_cluster and existing_cluster and candidate_cluster == existing_cluster:
            penalty += 0.45

    return min(penalty, 0.95)


def select_top_agents(agents, limit=3, order=None):
    """
    Select best available agents before execution.

    Foundation agents are NOT a fallback anymore.
    They are protocol infrastructure and compete through the same score,
    unless trust_preference says otherwise.
    """
    min_capability_match = 0.70

    available = []
    for a in agents:
        if not bool(a.get("available", True)):
            continue

        if order:
            capability_match = compute_capability_match_score(a, order)

            agent_type = str(a.get("agent_type", "") or "").lower()
            capabilities = parse_json_list(a.get("capabilities"))

            # Foundation agents are protocol infrastructure.
            # If legacy cloud records lack explicit capabilities, do not exclude them.
            if (
                capability_match < min_capability_match
                and not (agent_type == "foundation" and not capabilities)
            ):
                continue

        available.append(a)

    ranked = sorted(
        available,
        key=lambda a: compute_buyer_agent_score(a, order or {}),
        reverse=True,
    )

    selected = []

    for candidate in ranked:
        base_score = compute_buyer_agent_score(candidate, order or {})

        routing_modifier_data = compute_seller_routing_modifier(candidate)

        if not routing_modifier_data.get("allowed", True):
            continue

        routing_modifier = float(
            routing_modifier_data.get("modifier", 0) or 0
        )

        base_score += routing_modifier

        candidate["_seller_routing_modifier"] = round(routing_modifier, 6)
        candidate["_seller_routing_reason"] = routing_modifier_data.get("reason")

        diversity_penalty = compute_cluster_diversity_penalty(
            candidate,
            selected,
        )

        final_score = base_score * (1.0 - diversity_penalty)

        candidate["_routing_base_score"] = round(base_score, 6)
        candidate["_routing_diversity_penalty"] = round(diversity_penalty, 6)
        candidate["_routing_final_score"] = round(final_score, 6)

        if diversity_penalty >= 0.80:
            continue

        selected.append(candidate)

        selected = sorted(
            selected,
            key=lambda a: a.get("_routing_final_score", 0),
            reverse=True,
        )[:limit]

    return selected



def extract_semantic_signals_from_text(text):
    """
    Lightweight canonical semantic extraction.

    Goal:
    - give web agents and structured agents a shared semantic language
    - improve consensus across heterogeneous agent outputs
    - avoid making consensus depend only on URLs
    """
    text_l = str(text or "").lower()

    entities = set()
    claims = set()
    signals = {}

    entity_aliases = {
        "BTC": ["btc", "bitcoin"],
        "ETH": ["eth", "ethereum"],
        "AI": ["ai", "artificial intelligence"],
        "LLM": ["llm", "local llm", "large language model"],
    }

    for entity, aliases in entity_aliases.items():
        if any(alias in text_l for alias in aliases):
            entities.add(entity)

    signal_keywords = {
        "risk": ["risk", "risky", "exposure", "danger", "drawdown"],
        "volatility": ["volatility", "volatile"],
        "liquidity": ["liquidity", "liquid", "liquidity sweep"],
        "leverage": ["leverage", "leveraged", "margin"],
        "technical_structure": ["technical", "trend", "support", "resistance", "moving average"],
        "macro": ["macro", "policy", "rates", "inflation", "m2", "global liquidity"],
        "regulation": ["regulation", "law", "legal", "compliance", "legislation"],
        "price": ["price", "budget", "cost", "cheap", "expensive"],
        "performance": ["performance", "gpu", "cpu", "ram", "vram", "benchmark"],
    }

    detected = []

    for signal, keywords in signal_keywords.items():
        if any(k in text_l for k in keywords):
            detected.append(signal)
            signals[signal] = "detected"
            claims.add(f"{signal}:detected")

    if "bullish" in text_l or "uptrend" in text_l or "rising trend" in text_l:
        signals["market_bias"] = "bullish"
        claims.add("market_bias:bullish")

    if "bearish" in text_l or "downtrend" in text_l or "decline" in text_l:
        signals["market_bias"] = "bearish"
        claims.add("market_bias:bearish")

    if "high" in text_l and "risk" in text_l:
        signals["risk_level"] = "high"
        claims.add("risk_level:high")

    if "medium" in text_l and "risk" in text_l:
        signals["risk_level"] = "medium"
        claims.add("risk_level:medium")

    if "low" in text_l and "risk" in text_l:
        signals["risk_level"] = "low"
        claims.add("risk_level:low")

    if detected:
        claims.add("topics:" + ",".join(sorted(detected)))

    return {
        "entities": sorted(entities),
        "claims": sorted(claims),
        "structured_signals": signals,
    }


def normalize_agent_delivery(data):
    """
    Canonical multi-agent delivery schema.

    Every agent output is normalized into the same structure before:
    - consensus
    - ranking
    - trust scoring
    - arbitration
    - payment release
    """

    if not isinstance(data, dict):
        return {
            "status": "error",
            "delivery_type": "invalid",
            "summary": "Agent returned a non-JSON response.",
            "recommendations": [],
            "final_recommendation": None,
            "confidence": 0,
            "sources": [],
            "claims": [],
            "metrics": {},
            "structured_signals": {},
            "entities": [],
            "raw": data,
        }

    payload = data.get("data") if isinstance(data.get("data"), dict) else data

    delivery_type = str(payload.get("type") or data.get("type") or "generic").lower()

    recommendations = payload.get("recommendations") or data.get("recommendations") or []

    if not recommendations and isinstance(payload.get("results"), list):
        recommendations = payload.get("results")

    normalized_sources = []

    for s in payload.get("results", []):
        if isinstance(s, dict):
            normalized_sources.append({
                "title": s.get("title"),
                "url": s.get("link") or s.get("url"),
                "source": s.get("source"),
                "snippet": s.get("snippet"),
            })

    for s in data.get("sources", []):
        if isinstance(s, dict):
            normalized_sources.append({
                "title": s.get("title"),
                "url": s.get("url"),
                "source": s.get("source"),
                "snippet": s.get("snippet"),
            })

    claims = []

    if payload.get("recommendation"):
        claims.append(str(payload.get("recommendation")))

    if payload.get("risk_level"):
        claims.append(f"risk_level:{payload.get('risk_level')}")

    if payload.get("volatility"):
        claims.append(f"volatility:{payload.get('volatility')}")

    metrics = {}

    for k in [
        "confidence",
        "risk_level",
        "volatility",
        "asset",
        "price",
        "score",
        "trend",
    ]:
        if payload.get(k) is not None:
            metrics[k] = payload.get(k)

    structured_signals = {}

    for k in [
        "recommendation",
        "trend",
        "bias",
        "market_regime",
        "risk_level",
    ]:
        if payload.get(k) is not None:
            structured_signals[k] = payload.get(k)

    entities = []

    for k in [
        "asset",
        "symbol",
        "company",
        "product",
        "topic",
    ]:
        if payload.get(k):
            entities.append(str(payload.get(k)))

    semantic_text_parts = []

    for field in [
        payload.get("summary"),
        payload.get("recommendation"),
        payload.get("final_recommendation"),
        data.get("summary"),
        data.get("final_recommendation"),
    ]:
        if field:
            semantic_text_parts.append(str(field))

    for item in recommendations:
        if isinstance(item, dict):
            for field in ["title", "reason", "snippet"]:
                if item.get(field):
                    semantic_text_parts.append(str(item.get(field)))

    semantic_text = " ".join(semantic_text_parts)

    extracted = extract_semantic_signals_from_text(semantic_text)

    claims = sorted(set(claims).union(set(extracted.get("claims", []))))
    entities = sorted(set(entities).union(set(extracted.get("entities", []))))

    structured_signals.update(
        extracted.get("structured_signals", {})
    )

    return {
        "status": data.get("status", "success"),
        "delivery_type": delivery_type,
        "summary": (
            data.get("summary")
            or payload.get("summary")
            or data.get("answer")
            or data.get("result")
            or ""
        ),
        "recommendations": recommendations,
        "final_recommendation": (
            data.get("final_recommendation")
            or payload.get("final_recommendation")
            or payload.get("recommendation")
            or data.get("best")
            or data.get("answer")
        ),
        "confidence": float(
            payload.get("confidence")
            or data.get("confidence")
            or 0.5
        ),
        "sources": normalized_sources,
        "claims": claims,
        "metrics": metrics,
        "structured_signals": structured_signals,
        "entities": entities,
        "raw": data,
    }




def is_foundation_agent(agent):
    agent_type = str(agent.get("agent_type", "") or "").lower()
    agent_id = str(agent.get("agent_id", "") or "").lower()

    return (
        agent_type == "foundation"
        or agent_id.startswith("buyer_foundation_")
        or agent_id.startswith("foundation_")
    )






def foundation_google_search(query, limit=5):
    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")

    if not query:
        return []

    if not api_key or not cse_id:
        return []

    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": cse_id,
                "q": query,
                "num": max(1, min(int(limit or 5), 10)),
            },
            timeout=15,
        )

        if r.status_code != 200:
            return []

        results = []
        for item in r.json().get("items", [])[:limit]:
            results.append({
                "source": "google_custom_search",
                "title": item.get("title"),
                "snippet": item.get("snippet"),
                "link": item.get("link"),
                "display_link": item.get("displayLink"),
            })

        return results

    except Exception:
        return []


def foundation_duckduckgo_search(query, limit=5):
    if not query:
        return []

    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )

        soup = BeautifulSoup(r.text, "html.parser")
        results = []

        for result in soup.select(".result")[:limit]:
            title = result.select_one(".result__title")
            snippet = result.select_one(".result__snippet")
            link = result.select_one("a.result__a")

            if title and link:
                results.append({
                    "source": "duckduckgo_html",
                    "title": title.get_text(strip=True),
                    "snippet": snippet.get_text(strip=True) if snippet else "",
                    "link": link.get("href"),
                    "display_link": None,
                })

        return results

    except Exception:
        return []


def foundation_web_evidence_search(query, limit=5):
    results = foundation_google_search(query, limit=limit)
    provider = "google_custom_search" if results else None

    if not results:
        results = foundation_duckduckgo_search(query, limit=limit)
        provider = "duckduckgo_html" if results else None

    return {
        "provider": provider or "none",
        "query": query,
        "result_count": len(results),
        "results": results,
    }


def foundation_groq_execute(agent, order, profile, phase="research"):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return None

    query = order.get("query") or ""
    buyer_intent = parse_json_dict(order.get("buyer_intent"))
    requirements = parse_json_dict(order.get("requirements"))

    web_evidence = {}
    if phase == "research":
        web_evidence = foundation_web_evidence_search(query, limit=5)

    if phase == "verification":
        system_prompt = """
You are an IAT Protocol foundation verification agent.

Core rules:
- You are controlled by IAT Protocol.
- You verify research evidence before any buyer delivery.
- Sellers are internal suppliers only.
- Never expose internal seller details to the buyer.
- Never claim live verification if you cannot actually verify live facts.
- Be strict, skeptical, and evidence-focused.
- Identify weak claims, missing sources, contradictions, stale information, and unsafe conclusions.
- Return valid JSON only.

Your output must include:
- summary
- verified_claims
- rejected_claims
- uncertain_claims
- source_quality
- confidence_adjustment
- final_confidence
- recommendations
- final_recommendation
- sources
- claims
- metrics
- structured_signals
- entities
"""
        expected_output = {
            "delivery_type": "foundation_verification",
            "summary": "verification summary",
            "verified_claims": [],
            "rejected_claims": [],
            "uncertain_claims": [],
            "source_quality": "low|medium|high",
            "confidence_adjustment": 0.0,
            "final_confidence": 0.0,
            "recommendations": [],
            "final_recommendation": "verification verdict",
            "confidence": 0.0,
            "sources": [],
            "claims": [],
            "metrics": {},
            "structured_signals": {},
            "entities": []
        }
    else:
        system_prompt = """
You are an IAT Protocol foundation research agent.

Core rules:
- You are controlled by IAT Protocol.
- You produce research evidence for the foundation layer.
- Sellers are internal suppliers only.
- Never expose internal seller details to the buyer.
- Do not invent sources.
- If live/current facts cannot be verified, clearly mark uncertainty.
- Prefer structured, comparable, buyer-useful evidence.
- Return valid JSON only.

For product/comparison/research requests, produce:
- summary
- ranked recommendations with reasons
- concrete comparison criteria
- claims with confidence
- sources when available
- uncertainty notes
- final recommendation
- entities
- metrics
- structured signals

Your output must include:
- summary
- recommendations
- final_recommendation
- confidence
- sources
- claims
- metrics
- structured_signals
- entities
"""
        expected_output = {
            "delivery_type": "foundation_web_research",
            "summary": "useful research summary",
            "recommendations": [
                {
                    "name": "",
                    "reason": "",
                    "estimated_price": None,
                    "pros": [],
                    "cons": [],
                    "confidence": 0.0
                }
            ],
            "final_recommendation": "best final answer",
            "confidence": 0.0,
            "sources": [],
            "claims": [],
            "metrics": {},
            "structured_signals": {},
            "entities": []
        }

    user_prompt = json.dumps({
        "phase": phase,
        "agent_id": agent.get("agent_id"),
        "foundation_role": agent.get("foundation_role"),
        "profile": profile,
        "query": query,
        "buyer_intent": buyer_intent,
        "requirements": requirements,
        "foundation_research_results": order.get("foundation_research_results"),
        "foundation_research_consensus": order.get("foundation_research_consensus"),
        "foundation_research_strength": order.get("foundation_research_strength"),
        "web_evidence": web_evidence,
        "expected_output": expected_output
    }, ensure_ascii=False)

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )

        if r.status_code != 200:
            return {
                "delivery_type": "foundation_groq_error",
                "summary": "Groq foundation execution failed before producing a usable result.",
                "recommendations": [],
                "final_recommendation": "Foundation Groq execution requires debugging before high-confidence delivery.",
                "confidence": 0.0,
                "sources": [],
                "claims": [],
                "metrics": {
                    "groq_status_code": r.status_code,
                    "groq_error_text": r.text[:1000],
                },
                "structured_signals": {
                    "provider": "groq",
                    "phase": phase,
                    "error": True,
                },
                "entities": [],
                "raw": {
                    "query": query,
                    "provider": "groq",
                    "phase": phase,
                    "status_code": r.status_code,
                    "error_text": r.text[:1000],
                },
            }

        content = r.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        if not isinstance(parsed, dict):
            return None

        # Normalize common Groq shapes into the protocol evidence schema.
        if not parsed.get("summary"):
            parsed["summary"] = (
                parsed.get("research_summary")
                or parsed.get("verification_summary")
                or parsed.get("answer")
                or parsed.get("result")
                or ""
            )

        if not parsed.get("recommendations"):
            if isinstance(parsed.get("ranked_recommendations"), list):
                parsed["recommendations"] = parsed.get("ranked_recommendations")
            elif isinstance(parsed.get("options"), list):
                parsed["recommendations"] = parsed.get("options")
            elif isinstance(parsed.get("results"), list):
                parsed["recommendations"] = parsed.get("results")

        if not parsed.get("final_recommendation"):
            parsed["final_recommendation"] = (
                parsed.get("best_choice")
                or parsed.get("verdict")
                or parsed.get("summary")
                or ""
            )

        if not parsed.get("confidence") and parsed.get("final_confidence") is not None:
            parsed["confidence"] = parsed.get("final_confidence")

        parsed.setdefault(
            "delivery_type",
            "foundation_verification" if phase == "verification" else "foundation_web_research"
        )
        parsed.setdefault("summary", "")
        parsed.setdefault("recommendations", [])
        parsed.setdefault("final_recommendation", parsed.get("summary") or "")
        parsed.setdefault("confidence", parsed.get("final_confidence", 0.65))
        parsed.setdefault("sources", [])
        parsed.setdefault("claims", [])
        parsed.setdefault("metrics", {})
        parsed.setdefault("structured_signals", {})

        parsed["structured_signals"].update({
            "engine": profile.get("engine"),
            "role": profile.get("role"),
            "specialty": profile.get("specialty"),
            "provider": "groq",
            "phase": phase,
        })

        parsed.setdefault("entities", [])
        parsed["raw"] = {
            "query": query,
            "execution_layer": "foundation_internal",
            "engine": profile.get("engine"),
            "provider": "groq",
            "phase": phase,
            "web_evidence": web_evidence,
        }

        parsed["web_evidence"] = web_evidence

        return parsed

    except Exception as exc:
        return {
            "delivery_type": "foundation_groq_exception",
            "summary": "Groq foundation execution raised an exception.",
            "recommendations": [],
            "final_recommendation": "Foundation Groq execution requires debugging before high-confidence delivery.",
            "confidence": 0.0,
            "sources": [],
            "claims": [],
            "metrics": {
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            },
            "structured_signals": {
                "provider": "groq",
                "phase": phase,
                "error": True,
            },
            "entities": [],
            "raw": {
                "query": query,
                "provider": "groq",
                "phase": phase,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            },
        }


def foundation_web_research_engine(agent, order, profile):
    execution_phase = str(order.get("execution_phase") or "").lower()
    foundation_role = str(agent.get("foundation_role") or profile.get("role") or "").lower()

    phase = "verification" if (
        execution_phase == "foundation_verification"
        or foundation_role == "verification"
    ) else "research"

    groq_result = foundation_groq_execute(
        agent,
        order,
        profile,
        phase=phase,
    )

    if groq_result:
        return groq_result

    query = order.get("query") or ""

    if phase == "verification":
        return {
            "delivery_type": "foundation_verification_fallback",
            "summary": "Foundation verification Groq execution unavailable; fallback verification result returned.",
            "verified_claims": [],
            "rejected_claims": [],
            "uncertain_claims": [],
            "source_quality": "unknown",
            "confidence_adjustment": -0.25,
            "final_confidence": 0.35,
            "recommendations": [],
            "final_recommendation": "Manual or stronger foundation verification required before high-confidence buyer delivery.",
            "confidence": 0.35,
            "sources": [],
            "claims": [
                {
                    "claim": "Verification Groq execution did not return a usable result.",
                    "confidence": 1.0
                }
            ],
            "metrics": {
                "foundation_verification_fallback": True
            },
            "structured_signals": {
                "engine": profile.get("engine"),
                "role": profile.get("role"),
                "specialty": profile.get("specialty"),
                "phase": phase,
                "provider": "fallback"
            },
            "entities": [],
            "raw": {
                "query": query,
                "execution_layer": "foundation_internal",
                "engine": profile.get("engine"),
                "phase": phase,
                "provider": "fallback"
            },
        }

    return {
        "delivery_type": "foundation_web_research",
        "summary": (
            "Foundation web research engine processed the buyer request "
            "inside the protocol execution layer."
        ),
        "recommendations": [],
        "final_recommendation": (
            f"Foundation web research result for query: {query}"
        ),
        "confidence": 0.70,
        "sources": [],
        "claims": [
            {
                "claim": "Request handled by internal foundation web research engine.",
                "confidence": 0.70,
            }
        ],
        "metrics": {
            "foundation_engine_confidence": 0.70,
        },
        "structured_signals": {
            "engine": profile.get("engine"),
            "role": profile.get("role"),
            "specialty": profile.get("specialty"),
        },
        "entities": [],
        "raw": {
            "query": query,
            "execution_layer": "foundation_internal",
            "engine": profile.get("engine"),
        },
    }


def foundation_product_ranking_engine(agent, order, profile):
    query = order.get("query") or ""

    return {
        "delivery_type": "foundation_product_ranking",
        "summary": (
            "Foundation product ranking engine processed the buyer request "
            "inside the protocol execution layer."
        ),
        "recommendations": [],
        "final_recommendation": (
            f"Foundation product ranking result for query: {query}"
        ),
        "confidence": 0.70,
        "sources": [],
        "claims": [
            {
                "claim": "Request handled by internal foundation product ranking engine.",
                "confidence": 0.70,
            }
        ],
        "metrics": {
            "foundation_engine_confidence": 0.70,
        },
        "structured_signals": {
            "engine": profile.get("engine"),
            "role": profile.get("role"),
            "specialty": profile.get("specialty"),
        },
        "entities": [],
        "raw": {
            "query": query,
            "execution_layer": "foundation_internal",
            "engine": profile.get("engine"),
        },
    }


def foundation_generic_engine(agent, order, profile):
    query = order.get("query") or ""

    return {
        "delivery_type": "foundation_generic",
        "summary": (
            "Generic foundation engine handled the request internally."
        ),
        "recommendations": [],
        "final_recommendation": (
            f"Generic foundation result for query: {query}"
        ),
        "confidence": 0.60,
        "sources": [],
        "claims": [],
        "metrics": {
            "foundation_engine_confidence": 0.60,
        },
        "structured_signals": {
            "engine": profile.get("engine"),
            "role": profile.get("role"),
            "specialty": profile.get("specialty"),
        },
        "entities": [],
        "raw": {
            "query": query,
            "execution_layer": "foundation_internal",
            "engine": profile.get("engine"),
        },
    }


def route_foundation_engine(agent, order):
    profile = get_foundation_agent_profile(agent)
    engine = profile.get("engine")

    if engine == "foundation_web_research":
        return foundation_web_research_engine(agent, order, profile)

    if engine == "foundation_product_ranking":
        return foundation_product_ranking_engine(agent, order, profile)

    return foundation_generic_engine(agent, order, profile)



def execute_foundation_agent_internal(agent, order):
    start = time.monotonic()
    latency = 0.0

    try:
        data = route_foundation_engine(agent, order)

        latency = max(time.monotonic() - start, 0)

        return {
            "agent_id": agent.get("agent_id"),
            "wallet": agent.get("wallet"),
            "latency": round(latency, 6),
            "reputation": agent.get("reputation", 0.95),
            "success_count": agent.get("success_count", 0),
            "failure_count": agent.get("failure_count", 0),
            "call_count": agent.get("call_count", 0),
            "win_count": agent.get("win_count", 0),
            "latency_total": agent.get("latency_total", 0.0),
            "trust_tier": agent.get("trust_tier", "free"),
            "stake_amount": agent.get("stake_amount", 0.0),
            "stake_required": agent.get("stake_required", 0.0),
            "risk_score": agent.get("risk_score", 0.0),
            "volume_total": agent.get("volume_total", 0.0),
            "honest_volume": agent.get("honest_volume", 0.0),
            "fraud_volume": agent.get("fraud_volume", 0.0),
            "dynamic_stake_required": agent.get("dynamic_stake_required", 0.0),
            "success": True,
            "data": data,
        }

    except Exception as e:
        latency = max(time.monotonic() - start, 0)

        return {
            "agent_id": agent.get("agent_id"),
            "wallet": agent.get("wallet"),
            "latency": round(latency, 6),
            "reputation": agent.get("reputation", 0.95),
            "success": False,
            "error": str(e),
        }



def call_agent(agent, order):
    if is_foundation_agent(agent):
        return execute_foundation_agent_internal(agent, order)

    start = time.monotonic()

    try:
        r = requests.post(
            f"{agent['url']}/execute",
            json={
                "order_id": order.get("order_id", "test"),
                "tx_signature": order.get("tx_signature") or "INTERNAL_TEST_EXECUTION",
                "query": order.get("query"),
                "service": order.get("service"),
                "buyer_intent": order.get("buyer_intent"),
                "requirements": order.get("requirements"),
                "buyer_context": order.get("buyer_context"),
                "delivery_format": {
                    "language": "en",
                    "mode": "buyer_friendly",
                    "expected_schema": {
                        "summary": "short explanation of what was found",
                        "recommendations": "ranked options with price, quality and reason",
                        "final_recommendation": "best final choice",
                        "confidence": "0 to 1"
                    }
                }
            },
            timeout=15,
        )

        latency = max(time.monotonic() - start, 0)

        base = {
            "agent_id": agent.get("agent_id"),
            "wallet": agent.get("wallet"),
            "latency": round(latency, 6),
            "reputation": agent.get("reputation", 0.5),
            "success_count": agent.get("success_count", 0),
            "failure_count": agent.get("failure_count", 0),
            "call_count": agent.get("call_count", 0),
            "win_count": agent.get("win_count", 0),
            "latency_total": agent.get("latency_total", 0),
            "trust_tier": agent.get("trust_tier", "free"),
            "stake_amount": agent.get("stake_amount", 0),
            "stake_required": agent.get("stake_required", 0),
            "risk_score": agent.get("risk_score", 0),
            "volume_total": agent.get("volume_total", 0),
            "honest_volume": agent.get("honest_volume", 0),
            "fraud_volume": agent.get("fraud_volume", 0),
            "dynamic_stake_required": agent.get("dynamic_stake_required", 0),
        }

        if r.status_code == 200:
            return {
                **base,
                "success": True,
                "data": normalize_agent_delivery(r.json()),
            }

        return {
            **base,
            "success": False,
            "error": r.text,
        }

    except Exception as e:
        latency = max(time.monotonic() - start, 0)

        error_text = str(e)
        failure_type = "timeout" if "timed out" in error_text.lower() or "timeout" in error_text.lower() else "execution_error"

        return {
            "agent_id": agent.get("agent_id"),
            "wallet": agent.get("wallet"),
            "success": False,
            "failure_type": failure_type,
            "latency": round(latency, 6),
            "reputation": agent.get("reputation", 0.5),
            "success_count": agent.get("success_count", 0),
            "failure_count": agent.get("failure_count", 0),
            "call_count": agent.get("call_count", 0),
            "win_count": agent.get("win_count", 0),
            "latency_total": agent.get("latency_total", 0),
            "trust_tier": agent.get("trust_tier", "free"),
            "stake_amount": agent.get("stake_amount", 0),
            "stake_required": agent.get("stake_required", 0),
            "risk_score": agent.get("risk_score", 0),
            "volume_total": agent.get("volume_total", 0),
            "honest_volume": agent.get("honest_volume", 0),
            "fraud_volume": agent.get("fraud_volume", 0),
            "dynamic_stake_required": agent.get("dynamic_stake_required", 0),
            "error": error_text,
        }


def multi_call(agents, order, max_workers=5):
    results = []

    # Do not call disabled / killed agents
    agents = [
        a for a in agents
        if bool(a.get("available", True))
    ]

    if not agents:
        return results

    workers = min(max_workers, len(agents))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(call_agent, agent, order)
            for agent in agents
            if agent.get("url") or is_foundation_agent(agent)
        ]

        for future in as_completed(futures):
            results.append(future.result())

    try:
        consensus = compute_consensus(results)

        overlap_by_agent = {
            item.get("agent_id"): float(item.get("overlap", 0) or 0)
            for item in consensus.get("agent_overlaps", [])
        }

        from iat.api.db import (
            update_agent_topic_stats_db,
            update_agent_consensus_stats_db,
            run_seller_risk_orchestration_db,
        )

        for result in results:
            agent_id = result.get("agent_id")
            if not agent_id:
                continue

            topics = extract_topics_from_result(result, order)

            consensus_score = float(consensus.get("score", 0) or 0)

            update_agent_topic_stats_db(
                agent_id,
                topics,
                success=bool(result.get("success")) or result.get("failure_type") == "timeout",
                consensus_score=consensus_score,
                overlap=overlap_by_agent.get(agent_id, 0),
                quality=compute_quality(result) if result.get("success") else 0,
            )

            update_agent_consensus_stats_db(
                agent_id,
                consensus_score,
            )

            run_seller_risk_orchestration_db(agent_id)

    except Exception:
        # Topic memory must never break execution.
        pass

    return results


def compute_quality(result):


    data = result.get("data", {}).get("data", {})
    results = data.get("results", [])

    quality = len(results)

    if results:
        first = results[0]
        if first.get("title"):
            quality += 1
        if first.get("snippet"):
            quality += 1
        if first.get("link"):
            quality += 1

    latency = result.get("latency", 1)
    latency_score = 1 / (latency + 0.001)

    return quality * 2 + latency_score


def build_final_buyer_delivery(best_result, all_results=None):
    if not best_result:
        return {
            "status": "failed",
            "summary": "No successful provider response was available.",
            "final_recommendation": None,
            "alternatives": [],
            "confidence": 0,
        }

    data = best_result.get("data", {}) or {}

    recommendations = data.get("recommendations", []) or []
    final_recommendation = data.get("final_recommendation")
    summary = data.get("summary") or ""
    sources = data.get("sources", []) or []

    raw_data = data.get("raw", {}).get("data", {})
    raw_results = raw_data.get("results", []) if isinstance(raw_data, dict) else []

    usable_raw_results = []
    for item in raw_results:
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        link = str(item.get("link", "")).strip()

        if not title or "no results found" in title.lower():
            continue
        if not link:
            continue

        usable_raw_results.append({
            "title": title,
            "snippet": snippet,
            "link": link,
            "source": item.get("source"),
        })

    if usable_raw_results and not summary:
        titles = " ".join(item["title"] for item in usable_raw_results).lower()
        snippets = " ".join(item["snippet"] for item in usable_raw_results).lower()
        combined = f"{titles} {snippets}"

        themes = []

        if any(w in combined for w in ["volatility", "volatile"]):
            themes.append("volatility")
        if any(w in combined for w in ["liquidity", "liquid"]):
            themes.append("liquidity")
        if any(w in combined for w in ["risk", "risks"]):
            themes.append("risk")
        if any(w in combined for w in ["technical", "trend", "moving averages", "support", "resistance"]):
            themes.append("technical market structure")
        if any(w in combined for w in ["macro", "m2", "global liquidity", "policy"]):
            themes.append("macro conditions")

        if themes:
            summary = (
                "The selected provider found relevant sources indicating that the request is mainly driven by "
                + ", ".join(themes[:4])
                + "."
            )
        else:
            summary = "The selected provider found relevant sources matching the buyer request."

    if usable_raw_results and not recommendations:
        recommendations = [
            {
                "title": item["title"],
                "reason": item["snippet"],
                "source": item["link"],
            }
            for item in usable_raw_results[:5]
        ]

    if usable_raw_results and not final_recommendation:
        combined = " ".join(
            (item["title"] + " " + item["snippet"])
            for item in usable_raw_results
        ).lower()

        if "bitcoin" in combined or "btc" in combined:
            final_recommendation = (
                "Treat BTC as a high-sensitivity market today: prioritize liquidity conditions, volatility, "
                "technical structure, and macro risk before making any decision."
            )
        elif "risk" in combined:
            final_recommendation = (
                "Use the result as a risk-focused research base and review the strongest cited sources before acting."
            )
        else:
            final_recommendation = (
                "Use the selected result as the best available research base, supported by the cited sources."
            )

    if usable_raw_results and not sources:
        sources = [
            {
                "title": item["title"],
                "url": item["link"],
                "source": item.get("source"),
            }
            for item in usable_raw_results[:5]
        ]

    alternatives = []
    for r in all_results or []:
        if not r.get("success"):
            continue

        d = r.get("data", {}) or {}
        if r.get("agent_id") == best_result.get("agent_id"):
            continue

        alternatives.append({
            "source_agent": r.get("agent_id"),
            "summary": d.get("summary"),
            "final_recommendation": d.get("final_recommendation"),
            "confidence": d.get("confidence", 0),
        })

    return {
        "status": "success",
        "summary": summary,
        "recommendations": recommendations,
        "final_recommendation": final_recommendation,
        "alternatives": alternatives[:3],
        "confidence": data.get("confidence", 0.5),
        "selection_score": best_result.get("selection_score"),
        "selection_reason": "Selected for the best balance of result quality, reliability, confidence, response speed and value.",
        "sources": sources,
    }


def compute_consensus_strength(results):
    """
    Compute high-level consensus strength across successful foundation results.

    This is protocol-facing trust metadata:
    - agreement_score
    - signal overlap
    - shared entities / claims
    - divergence detection
    - confidence-weighted score
    """
    valid = [r for r in results if r.get("success")]

    if not valid:
        return {
            "agreement_score": 0,
            "signal_overlap": 0,
            "confidence_weighted": 0,
            "divergence_detected": True,
            "shared_entities": [],
            "shared_claims": [],
            "agents_count": 0,
        }

    entity_sets = []
    claim_sets = []
    confidences = []

    for r in valid:
        data = r.get("data") or {}

        entities = set(str(x).lower() for x in data.get("entities", []) if x)
        claims = set(str(x).lower() for x in data.get("claims", []) if x)

        structured = data.get("structured_signals") or {}
        for k, v in structured.items():
            claims.add(str(k).lower())
            if v:
                claims.add(str(v).lower())

        metrics = data.get("metrics") or {}
        for k, v in metrics.items():
            claims.add(str(k).lower())
            if isinstance(v, str):
                claims.add(str(v).lower())

        entity_sets.append(entities)
        claim_sets.append(claims)

        try:
            confidences.append(float(data.get("confidence", 0.5) or 0.5))
        except Exception:
            confidences.append(0.5)

    shared_entities = set.intersection(*entity_sets) if entity_sets else set()
    shared_claims = set.intersection(*claim_sets) if claim_sets else set()

    all_entities = set.union(*entity_sets) if entity_sets else set()
    all_claims = set.union(*claim_sets) if claim_sets else set()

    entity_overlap = (
        len(shared_entities) / len(all_entities)
        if all_entities else 0
    )

    claim_overlap = (
        len(shared_claims) / len(all_claims)
        if all_claims else 0
    )

    confidence_weighted = (
        sum(confidences) / len(confidences)
        if confidences else 0
    )

    signal_overlap = (
        entity_overlap * 0.35 +
        claim_overlap * 0.65
    )

    agreement_score = (
        signal_overlap * 0.55 +
        confidence_weighted * 0.45
    )

    if agreement_score >= 0.70:
        consensus_level = "strong"
    elif agreement_score >= 0.45:
        consensus_level = "moderate"
    else:
        consensus_level = "weak"

    divergence_detected = agreement_score < 0.45

    return {
        "consensus_level": consensus_level,
        "agreement_score": round(agreement_score, 4),
        "signal_overlap": round(signal_overlap, 4),
        "entity_overlap": round(entity_overlap, 4),
        "claim_overlap": round(claim_overlap, 4),
        "confidence_weighted": round(confidence_weighted, 4),
        "divergence_detected": divergence_detected,
        "shared_entities": sorted(shared_entities),
        "shared_claims": sorted(shared_claims),
        "agents_count": len(valid),
    }


def select_best_result(results):
    valid = [r for r in results if r.get("success")]

    if not valid:
        return None

    consensus = compute_consensus(valid)
    suspicious = set(consensus.get("suspicious_agents", []))

    max_quality = max(compute_quality(r) for r in valid) or 1
    prices = [float(r.get("price", r.get("price_iat", 1)) or 1) for r in valid]
    min_price = min(prices) if prices else 1

    scored = []

    for r in valid:
        agent_id = r.get("agent_id")

        raw_data = r.get("data", {}).get("raw", {}).get("data", {})
        raw_results = raw_data.get("results", []) if isinstance(raw_data, dict) else []

        no_usable_results = False
        if not raw_results:
            no_usable_results = True
        elif len(raw_results) == 1:
            first = raw_results[0] or {}
            title = str(first.get("title", "")).lower()
            snippet = str(first.get("snippet", "")).lower()
            link = str(first.get("link", "")).strip()
            if "no results found" in title or "no usable result" in snippet or not link:
                no_usable_results = True

        quality_raw = compute_quality(r)
        quality_score = min(1.0, quality_raw / max_quality)

        reputation_score = float(r.get("reputation", 0.5) or 0.5)

        price = float(r.get("price", r.get("price_iat", 1)) or 1)
        price_score = min(1.0, min_price / price) if price > 0 else 0

        latency = float(r.get("latency", 5) or 5)
        latency_score = min(1.0, 1 / (latency + 0.001))

        overlap_score = 0
        risk_score = float(r.get("risk_score", 0) or 0)

        for item in consensus.get("agent_overlaps", []):
            if item.get("agent_id") == agent_id:
                overlap_score = float(item.get("overlap", 0) or 0)
                break

        for item in consensus.get("agent_trust", []):
            if item.get("agent_id") == agent_id:
                risk_score = float(item.get("risk_score", risk_score) or 0)
                break

        final_score = (
            overlap_score * 0.35 +
            reputation_score * 0.20 +
            quality_score * 0.30 +
            price_score * 0.10 +
            latency_score * 0.05
        )

        if no_usable_results:
            final_score = final_score * 0.01

        final_score = final_score * max(0.05, 1 - risk_score)

        if agent_id in suspicious:
            final_score = final_score * 0.10

        r["selection_score"] = round(final_score, 6)
        r["selection_score_details"] = {
            "overlap_score": round(overlap_score, 4),
            "reputation_score": round(reputation_score, 4),
            "quality_score": round(quality_score, 4),
            "price_score": round(price_score, 4),
            "latency_score": round(latency_score, 4),
            "risk_score": round(risk_score, 4),
            "suspicious": agent_id in suspicious,
            "no_usable_results": no_usable_results,
        }

        scored.append((final_score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    best = scored[0][1]
    best["final_buyer_delivery"] = build_final_buyer_delivery(best, valid)

    return best

def extract_topics_from_result(result, order=None):
    """
    Extract generic semantic topics from an agent result.

    Topics are not hardcoded vertical routing categories.
    They are emergent semantic signals from:
    - entities
    - claims
    - structured signals
    - metrics
    - buyer intent requirements
    """
    topics = set()

    order = order or {}
    intent = order.get("buyer_intent") or {}
    requirements = order.get("requirements") or {}

    data = result.get("data", {}) or {}

    for item in data.get("entities", []) or []:
        if item:
            topics.add(str(item).lower())

    for claim in data.get("claims", []) or []:
        claim = str(claim or "").lower()
        if ":" in claim:
            topics.add(claim.split(":", 1)[0])
        elif claim:
            topics.add(claim[:80])

    for key, value in (data.get("structured_signals", {}) or {}).items():
        if key:
            topics.add(str(key).lower())
        if value and str(value).lower() not in ["detected", "true", "false", "none"]:
            topics.add(str(value).lower())

    for key, value in (data.get("metrics", {}) or {}).items():
        if key:
            topics.add(str(key).lower())
        if key in ["asset", "symbol", "topic", "product", "company"] and value:
            topics.add(str(value).lower())

    for key, value in requirements.items():
        if isinstance(value, (str, int, float)):
            topics.add(str(value).lower())
        elif isinstance(value, list):
            for v in value:
                topics.add(str(v).lower())

    for item in intent.get("preferred_specialties", []) or []:
        topics.add(str(item).lower())

    for item in intent.get("required_capabilities", []) or []:
        topics.add(str(item).lower())

    noisy_topics = {
        "topics",
        "detected",
        "true",
        "false",
        "none",
        "premium",
        "high",
        "medium",
        "low",
        "normal",
        "balanced",
        "fastest",
        "safest",
        "cheapest",
        "consensus_required",
        "foundation_allowed",
        "foundation_only",
        "open_market",
    }

    cleaned = []
    for topic in topics:
        topic = topic.strip().lower()
        if not topic:
            continue
        if topic in noisy_topics:
            continue
        if len(topic) < 2:
            continue
        if len(topic) > 80:
            topic = topic[:80]
        cleaned.append(topic)

    return sorted(set(cleaned))


def compute_consensus(results):
    valid = [r for r in results if r.get("success")]

    if not valid:
        return {
            "status": "failed",
            "score": 0,
            "valid_agents": 0,
            "reason": "no_successful_results",
            "suspicious_agents": [],
            "collusion_flags": [],
        }

    agent_sets = []

    # --- BUILD AGENTS ---
    for r in valid:
        wrapper = r.get("data", {}) or {}

        data = wrapper.get("data", {}) or {}

        # Render agents often return normalized data under raw.data.
        raw_data = wrapper.get("raw", {}).get("data", {})
        if isinstance(raw_data, dict) and raw_data:
            data = raw_data

        items = data.get("results", []) if isinstance(data, dict) else []

        links = set()
        domains = set()
        title_words = set()

        stopwords = {
            "the", "and", "for", "with", "from",
            "this", "that", "into", "your",
            "best", "top", "guide", "review",
            "reviews", "hotel", "hotels",
            "paris", "france"
        }

        def normalize_token(token):
            token = token.strip().lower()

            token = token.strip(".,:;!?()[]{}'\"")

            if token.endswith("s") and len(token) > 4:
                token = token[:-1]

            if token.endswith("ing") and len(token) > 5:
                token = token[:-3]

            return token

        for item in items[:5]:
            link = item.get("link")
            title = item.get("title") or ""
            snippet = item.get("snippet") or ""

            if link:
                clean_link = link.strip().lower()
                links.add(clean_link)

                domain = clean_link
                domain = domain.replace("https://", "").replace("http://", "")
                domain = domain.replace("//duckduckgo.com/l/?uddg=", "")
                domain = domain.split("/")[0]
                domain = domain.split("%2f")[0]
                domain = domain.split("&")[0]
                domains.add(domain)

            text_blob = (title + " " + snippet).lower()

            for raw_token in text_blob.replace("-", " ").replace("_", " ").split():
                token = normalize_token(raw_token)

                if (
                    len(token) >= 3
                    and token not in stopwords
                    and not token.isdigit()
                ):
                    title_words.add(token)

        query = (
            data.get("query")
            or r.get("query")
            or ""
        ).lower()

        query_words = set()
        for raw_token in query.replace("-", " ").replace("_", " ").split():
            token = normalize_token(raw_token)
            if (
                len(token) >= 3
                and token not in stopwords
                and not token.isdigit()
            ):
                query_words.add(token)

        query_relevance = (
            len(title_words.intersection(query_words)) / len(query_words)
            if query_words else 0
        )

        result_validity = 0

        # Web/search evidence
        if len(items) >= 3:
            result_validity += 0.35
        if links:
            result_validity += 0.25
        if domains:
            result_validity += 0.20
        if title_words:
            result_validity += 0.20

        # Structured/analytic evidence
        normalized = r.get("data", {}) or {}

        if normalized.get("claims"):
            result_validity += 0.25
        if normalized.get("entities"):
            result_validity += 0.15
        if normalized.get("structured_signals"):
            result_validity += 0.25
        if normalized.get("metrics"):
            result_validity += 0.25
        if normalized.get("final_recommendation"):
            result_validity += 0.20

        result_validity = min(result_validity, 1.0)

        rep = float(r.get("reputation", 0.5))
        successes = int(r.get("success_count", 0) or 0)
        failures = int(r.get("failure_count", 0) or 0)

        success_factor = 1 + min(successes * 0.02, 0.20)
        failure_factor = 1 / (1 + failures)

        base_weight = rep * success_factor * failure_factor

        normalized = r.get("data", {}) or {}

        claims = set(
            str(x).lower()
            for x in normalized.get("claims", [])
            if x
        )

        entities = set(
            str(x).lower()
            for x in normalized.get("entities", [])
            if x
        )

        structured_signals = {
            str(k).lower(): str(v).lower()
            for k, v in (normalized.get("structured_signals", {}) or {}).items()
        }

        metrics = {
            str(k).lower(): str(v).lower()
            for k, v in (normalized.get("metrics", {}) or {}).items()
        }

        recommendations_text = set()

        for rec in normalized.get("recommendations", []):
            if isinstance(rec, dict):
                for field in ["title", "reason", "snippet"]:
                    val = rec.get(field)
                    if val:
                        recommendations_text.add(str(val).lower())

        final_recommendation = str(
            normalized.get("final_recommendation") or ""
        ).lower()

        agent_sets.append({
            "agent_id": r.get("agent_id"),
            "wallet": r.get("wallet"),
            "trust_tier": r.get("trust_tier", "free"),
            "stake_amount": float(r.get("stake_amount", 0) or 0),
            "stake_required": float(r.get("stake_required", 0) or 0),
            "risk_score": float(r.get("risk_score", 0) or 0),

            "links": links,
            "domains": domains,
            "title_words": title_words,

            "claims": claims,
            "entities": entities,
            "structured_signals": structured_signals,
            "metrics": metrics,
            "recommendations_text": recommendations_text,
            "final_recommendation": final_recommendation,

            "query_relevance": round(query_relevance, 4),
            "result_validity": round(result_validity, 4),
            "base_weight": base_weight,
            "weight": base_weight,
        })

    # --- WALLET DIAGNOSTIC ONLY ---
    wallet_weights = {}
    for agent in agent_sets:
        w = agent.get("wallet") or "UNKNOWN"
        wallet_weights.setdefault(w, 0)
        wallet_weights[w] += agent["weight"]

    # --- CALCULATE CONSENSUS OVERLAPS ---
    for agent in agent_sets:
        links = agent.get("links", set())
        domains = agent.get("domains", set())
        title_words = agent.get("title_words", set())
        query_relevance = float(agent.get("query_relevance", 0) or 0)
        result_validity = float(agent.get("result_validity", 0) or 0)

        claims = agent.get("claims", set())
        entities = agent.get("entities", set())
        structured_signals = agent.get("structured_signals", {})
        metrics = agent.get("metrics", {})
        recommendations_text = agent.get("recommendations_text", set())

        other_links = set()
        other_domains = set()
        other_title_words = set()
        other_claims = set()
        other_entities = set()
        other_recommendations_text = set()
        other_signal_pairs = set()
        other_metric_pairs = set()

        for other in agent_sets:
            if other["agent_id"] != agent["agent_id"]:
                other_links.update(other.get("links", set()))
                other_domains.update(other.get("domains", set()))
                other_title_words.update(other.get("title_words", set()))
                other_claims.update(other.get("claims", set()))
                other_entities.update(other.get("entities", set()))
                other_recommendations_text.update(other.get("recommendations_text", set()))

                other_signal_pairs.update(
                    set((other.get("structured_signals", {}) or {}).items())
                )
                other_metric_pairs.update(
                    set((other.get("metrics", {}) or {}).items())
                )

        link_overlap = len(links.intersection(other_links)) / len(links) if links else 0
        domain_overlap = len(domains.intersection(other_domains)) / len(domains) if domains else 0
        title_overlap = len(title_words.intersection(other_title_words)) / len(title_words) if title_words else 0

        claims_overlap = len(claims.intersection(other_claims)) / len(claims) if claims else 0
        entities_overlap = len(entities.intersection(other_entities)) / len(entities) if entities else 0

        signal_pairs = set((structured_signals or {}).items())
        metric_pairs = set((metrics or {}).items())

        signal_overlap = (
            len(signal_pairs.intersection(other_signal_pairs)) / len(signal_pairs)
            if signal_pairs else 0
        )

        metrics_overlap = (
            len(metric_pairs.intersection(other_metric_pairs)) / len(metric_pairs)
            if metric_pairs else 0
        )

        recommendation_overlap = 0
        if recommendations_text and other_recommendations_text:
            shared_tokens = set()
            own_tokens = set()

            for txt in recommendations_text:
                own_tokens.update(txt.replace("-", " ").replace("_", " ").split())

            for txt in other_recommendations_text:
                shared_tokens.update(txt.replace("-", " ").replace("_", " ").split())

            own_tokens = {t for t in own_tokens if len(t) >= 4}
            shared_tokens = {t for t in shared_tokens if len(t) >= 4}

            recommendation_overlap = (
                len(own_tokens.intersection(shared_tokens)) / len(own_tokens)
                if own_tokens else 0
            )

        final_recommendation_overlap = 0
        if final_recommendation:
            own_tokens = {
                t for t in final_recommendation.replace("-", " ").replace("_", " ").split()
                if len(t) >= 4
            }

            other_tokens = set()
            for other in agent_sets:
                if other["agent_id"] == agent["agent_id"]:
                    continue

                other_tokens.update(
                    t for t in str(other.get("final_recommendation") or "")
                    .replace("-", " ")
                    .replace("_", " ")
                    .split()
                    if len(t) >= 4
                )

            final_recommendation_overlap = (
                len(own_tokens.intersection(other_tokens)) / len(own_tokens)
                if own_tokens else 0
            )

        fake_penalty = 0
        if any("fake" in link for link in links) or any("fake" in word for word in title_words):
            fake_penalty = 0.8

        web_overlap = (
            link_overlap * 0.15 +
            domain_overlap * 0.25 +
            title_overlap * 0.60
        )

        semantic_overlap = (
            claims_overlap * 0.20 +
            entities_overlap * 0.15 +
            signal_overlap * 0.20 +
            metrics_overlap * 0.10 +
            recommendation_overlap * 0.15 +
            final_recommendation_overlap * 0.20
        )

        independent_quality = (
            query_relevance * 0.45 +
            result_validity * 0.55
        )

        if query_relevance < 0.15:
            independent_quality = 0

        if result_validity < 0.30:
            independent_quality = 0

        # Multi-format consensus:
        # - web agents agree through sources/titles
        # - analytic agents agree through claims/signals/entities/metrics
        # - high-quality independent results still count
        overlap = (
            web_overlap * 0.25 +
            semantic_overlap * 0.35 +
            independent_quality * 0.40
        )

        overlap = max(0, overlap - fake_penalty)

        agent["overlap"] = round(overlap, 4)
        agent["overlap_details"] = {
            "link_overlap": round(link_overlap, 4),
            "domain_overlap": round(domain_overlap, 4),
            "title_overlap": round(title_overlap, 4),
            "claims_overlap": round(claims_overlap, 4),
            "entities_overlap": round(entities_overlap, 4),
            "signal_overlap": round(signal_overlap, 4),
            "metrics_overlap": round(metrics_overlap, 4),
            "recommendation_overlap": round(recommendation_overlap, 4),
            "final_recommendation_overlap": round(final_recommendation_overlap, 4),
            "web_overlap": round(web_overlap, 4),
            "semantic_overlap": round(semantic_overlap, 4),
            "query_relevance": round(query_relevance, 4),
            "result_validity": round(result_validity, 4),
            "independent_quality": round(independent_quality, 4),
            "fake_penalty": round(fake_penalty, 4),
        }

    # --- DYNAMIC WEIGHT BY BEHAVIOR ---
    for agent in agent_sets:
        overlap = float(agent.get("overlap", 0))
        agent["weight"] = agent["weight"] * (0.2 + 0.8 * overlap)

    # --- HYBRID TRUST CONSENSUS ADJUSTMENT ---
    for agent in agent_sets:
        overlap = float(agent.get("overlap", 0) or 0)
        risk = float(agent.get("risk_score", 0) or 0)
        stake = float(agent.get("stake_amount", 0) or 0)
        required = float(agent.get("stake_required", 0) or 0)

        # behavior risk overrides passive DB risk.
        # Low overlap alone is not suspicious: decentralized agents may use different sources.
        # Penalize only clearly unusable/fake results.
        result_validity = float(agent.get("result_validity", 0) or 0)

        if result_validity <= 0:
            risk = max(risk, 0.7)

        if overlap == 0 and fake_penalty > 0:
            risk = max(risk, 0.9)

        agent["effective_risk_score"] = round(min(risk, 1.0), 4)

        # risk penalty
        agent["weight"] = agent["weight"] * max(0.1, 1 - min(risk, 1.0) * 0.5)

        # missing required stake penalty
        if required > 0 and stake < required:
            agent["weight"] = agent["weight"] * 0.7
            agent["trust_tier"] = "stake_required"

        # stake confidence bonus
        if stake >= 1000:
            agent["weight"] = agent["weight"] * 1.15
            agent["trust_tier"] = "premium"
        elif stake >= 100:
            agent["weight"] = agent["weight"] * 1.07
            agent["trust_tier"] = "standard"
        elif stake >= 10 and agent.get("trust_tier") == "free":
            agent["trust_tier"] = "recovery"

    # --- INTELLIGENT ANTI-SYBIL WALLET CAP ---
    # Same wallet is allowed.
    # But if multiple wallets participate, one wallet cannot dominate the consensus.
    unique_wallets = set((a.get("wallet") or "UNKNOWN") for a in agent_sets)

    sybil_wallet_caps = {}

    if len(unique_wallets) > 1:
        pre_cap_total = sum(a["weight"] for a in agent_sets)
        max_wallet_share = 0.65
        max_wallet_weight = pre_cap_total * max_wallet_share

        wallet_totals = {}
        for agent in agent_sets:
            wallet = agent.get("wallet") or "UNKNOWN"
            wallet_totals.setdefault(wallet, 0)
            wallet_totals[wallet] += agent["weight"]

        for wallet, wallet_weight in wallet_totals.items():
            if wallet_weight > max_wallet_weight:
                reduction_factor = max_wallet_weight / wallet_weight
                sybil_wallet_caps[wallet] = {
                    "original_weight": round(wallet_weight, 4),
                    "capped_weight": round(max_wallet_weight, 4),
                    "reduction_factor": round(reduction_factor, 4),
                    "reason": "wallet_dominance_cap",
                }

                for agent in agent_sets:
                    if (agent.get("wallet") or "UNKNOWN") == wallet:
                        agent["weight"] = agent["weight"] * reduction_factor

    total_weight = sum(a["weight"] for a in agent_sets)

    weighted_score = 0
    for agent in agent_sets:
        weighted_score += agent["overlap"] * agent["weight"]

    score = weighted_score / total_weight if total_weight > 0 else 0

    high_overlap_agents = [
        a for a in agent_sets
        if float(a.get("overlap", 0) or 0) >= 0.75
    ]

    usable_agents = [
        a for a in agent_sets
        if (
            float(a.get("result_validity", 0) or 0) >= 0.30
            and float(a.get("query_relevance", 0) or 0) >= 0.15
            and float(a.get("overlap", 0) or 0) > 0
        )
    ]

    low_risk_usable_agents = [
        a for a in usable_agents
        if float(a.get("effective_risk_score", a.get("risk_score", 0)) or 0) < 0.5
    ]

    quorum_passed = (
        (score >= 0.60 and len(usable_agents) >= 2)
        or len(high_overlap_agents) >= 2
        or (
            len(low_risk_usable_agents) >= 2
            and score >= 0.30
        )
    )

    if len(usable_agents) == 0:
        status = "failed"
        consensus_failure_reason = "no_usable_foundation_results"
    elif score < 0.10:
        status = "failed"
        consensus_failure_reason = "consensus_score_too_low"
    else:
        status = "passed" if quorum_passed else "suspicious"
        consensus_failure_reason = None

    suspicious_agents = [
        agent["agent_id"]
        for agent in agent_sets
        if (
            float(agent.get("effective_risk_score", agent.get("risk_score", 0)) or 0) >= 0.7
            and float(agent.get("result_validity", 0) or 0) <= 0
        )
    ]

    # --- WALLET COLLUSION DIAGNOSTIC ---
    wallet_groups = {}
    for agent in agent_sets:
        wallet = agent.get("wallet") or "UNKNOWN"
        wallet_groups.setdefault(wallet, []).append(agent)

    collusion_flags = []

    def overlap_between(a, b):
        links_a = a.get("links", set())
        links_b = b.get("links", set())

        if not links_a or not links_b:
            return 0

        return len(links_a.intersection(links_b)) / max(len(links_a), 1)

    for wallet, group in wallet_groups.items():
        if len(group) < 2:
            continue

        other_agents = [
            a for a in agent_sets
            if (a.get("wallet") or "UNKNOWN") != wallet
        ]

        if not other_agents:
            continue

        internal_scores = []
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                internal_scores.append(overlap_between(a, b))

        external_scores = []
        for a in group:
            for b in other_agents:
                external_scores.append(overlap_between(a, b))

        internal_avg = sum(internal_scores) / len(internal_scores) if internal_scores else 0
        external_avg = sum(external_scores) / len(external_scores) if external_scores else 0

        if internal_avg >= 0.8 and external_avg <= 0.3:
            for agent in group:
                collusion_flags.append({
                    "agent_id": agent.get("agent_id"),
                    "wallet": wallet,
                    "internal_overlap": round(internal_avg, 4),
                    "external_overlap": round(external_avg, 4),
                    "reason": "same_wallet_cluster_low_external_agreement",
                })

    collusion_agent_ids = set(flag["agent_id"] for flag in collusion_flags)
    suspicious_agents = list(set(suspicious_agents).union(collusion_agent_ids))

    return {
        "status": status,
        "score": round(score, 4),
        "total_weight": round(total_weight, 4),
        "weighted_overlap": round(weighted_score, 4),
        "valid_agents": len(valid),
        "consensus_failure_reason": consensus_failure_reason,
        "consensus_gates": {
            "usable_agents": len(usable_agents),
            "low_risk_usable_agents": len(low_risk_usable_agents),
            "high_overlap_agents": len(high_overlap_agents),
            "quorum_passed": quorum_passed,
        },
        "agent_overlaps": [
            {
                "agent_id": a["agent_id"],
                "overlap": a["overlap"],
                "base_weight": round(a["base_weight"], 4),
                "weight": round(a["weight"], 4),
                "overlap_details": a.get("overlap_details", {}),
            }
            for a in agent_sets
        ],
        "sybil_wallet_caps": sybil_wallet_caps,
        "agent_trust": [
            {
                "agent_id": a["agent_id"],
                "tier": a.get("trust_tier", "free"),
                "stake_amount": a.get("stake_amount", 0),
                "stake_required": a.get("stake_required", 0),
                "risk_score": a.get("effective_risk_score", a.get("risk_score", 0)),
            }
            for a in agent_sets
        ],
        "wallet_weights": {
            wallet: round(weight, 4)
            for wallet, weight in wallet_weights.items()
        },
        "suspicious_agents": suspicious_agents,
        "collusion_flags": collusion_flags,
    }



def compute_seller_routing_modifier(agent):
    seller_status = str(agent.get("seller_status", "") or "").lower()
    trust_tier = str(agent.get("trust_tier", "") or "").lower()

    risk_score = float(agent.get("risk_score", 0) or 0)
    containment_count = int(agent.get("containment_count", 0) or 0)
    economic_penalty_level = int(agent.get("economic_penalty_level", 0) or 0)

    latent_risk_score = float(agent.get("latent_risk_score", 0) or 0)
    mutation_score = float(agent.get("mutation_score", 0) or 0)
    contagion_score = float(agent.get("contagion_score", 0) or 0)
    quarantine_pressure = float(agent.get("quarantine_pressure", 0) or 0)
    graph_position_score = float(agent.get("graph_position_score", 0) or 0)
    adaptive_trust_score = float(agent.get("adaptive_trust_score", 0.5) or 0.5)

    if seller_status in ["contained", "banned", "rejected"]:
        return {
            "allowed": False,
            "modifier": -999,
            "reason": "seller_status_blocked",
        }

    modifier = 0.0

    if trust_tier == "premium":
        modifier += 0.12
    elif trust_tier == "trusted":
        modifier += 0.08
    elif trust_tier == "new":
        modifier += 0.0
    elif trust_tier == "restricted":
        modifier -= 0.25

    if seller_status in ["watchlist", "restricted"]:
        modifier -= 0.25

    modifier -= min(risk_score * 0.35, 0.35)
    modifier -= min(containment_count * 0.15, 0.45)
    modifier -= min(economic_penalty_level * 0.10, 0.50)

    modifier -= min(latent_risk_score * 0.18, 0.18)
    modifier -= min(mutation_score * 0.14, 0.14)
    modifier -= min(contagion_score * 0.16, 0.16)
    modifier -= min(quarantine_pressure * 0.20, 0.20)
    modifier -= min(graph_position_score * 0.08, 0.08)

    if adaptive_trust_score >= 0.75:
        modifier += 0.05
    elif adaptive_trust_score <= 0.30:
        modifier -= 0.08

    return {
        "allowed": True,
        "modifier": round(modifier, 6),
        "reason": "seller_routing_modifier_applied",
    }


