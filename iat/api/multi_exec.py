import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


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
        - stake_gap_penalty
        - adaptive_fraud_penalty
    )

    return round(score, 6)


def select_top_agents(agents, limit=3):
    """
    Select best available agents before execution.
    This reduces cost and avoids calling disabled/bad agents.
    """
    available_agents = [
        a for a in agents
        if bool(a.get("available", True))
    ]

    ranked = sorted(
        available_agents,
        key=compute_agent_market_score,
        reverse=True,
    )

    return ranked[:limit]



def call_agent(agent, order):
    start = time.monotonic()

    try:
        r = requests.post(
            f"{agent['url']}/execute",
            json={
                "order_id": order.get("order_id", "test"),
                "tx_signature": order.get("tx_signature"),
                "query": order.get("query"),
            },
            timeout=15,
        )

        latency = max(time.monotonic() - start, 0)

        if r.status_code == 200:
            return {
                "agent_id": agent.get("agent_id"),
                "wallet": agent.get("wallet"),  # ✅ AJOUT
                "success": True,
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
                "trust_tier": agent.get("trust_tier", "free"),
                "stake_amount": agent.get("stake_amount", 0),
                "stake_required": agent.get("stake_required", 0),
                "risk_score": agent.get("risk_score", 0),
                "volume_total": agent.get("volume_total", 0),
                "honest_volume": agent.get("honest_volume", 0),
                "fraud_volume": agent.get("fraud_volume", 0),
                "dynamic_stake_required": agent.get("dynamic_stake_required", 0),
                "data": r.json(),
            }

        return {
            "agent_id": agent.get("agent_id"),
            "success": False,
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
            "error": r.text,
        }

    except Exception as e:
        latency = max(time.monotonic() - start, 0)
    return {
        "agent_id": agent.get("agent_id"),
        "success": False,
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
        "error": str(e),
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
            if agent.get("url")
        ]

        for future in as_completed(futures):
            results.append(future.result())

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
            overlap_score * 0.40 +
            reputation_score * 0.25 +
            quality_score * 0.20 +
            price_score * 0.10 +
            latency_score * 0.05
        )

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
        }

        scored.append((final_score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    return scored[0][1]

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
        data = r.get("data", {}).get("data", {})
        items = data.get("results", [])

        links = set()
        domains = set()
        title_words = set()

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
            for token in text_blob.replace("-", " ").replace("_", " ").split():
                token = token.strip(".,:;!?()[]{}'\"")
                if len(token) >= 4:
                    title_words.add(token)

        rep = float(r.get("reputation", 0.5))
        successes = int(r.get("success_count", 0) or 0)
        failures = int(r.get("failure_count", 0) or 0)

        success_factor = 1 + min(successes * 0.02, 0.20)
        failure_factor = 1 / (1 + failures)

        base_weight = rep * success_factor * failure_factor

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

        other_links = set()
        other_domains = set()
        other_title_words = set()

        for other in agent_sets:
            if other["agent_id"] != agent["agent_id"]:
                other_links.update(other.get("links", set()))
                other_domains.update(other.get("domains", set()))
                other_title_words.update(other.get("title_words", set()))

        link_overlap = len(links.intersection(other_links)) / len(links) if links else 0
        domain_overlap = len(domains.intersection(other_domains)) / len(domains) if domains else 0
        title_overlap = len(title_words.intersection(other_title_words)) / len(title_words) if title_words else 0

        fake_penalty = 0
        if any("fake" in link for link in links) or any("fake" in word for word in title_words):
            fake_penalty = 0.8

        overlap = (
            link_overlap * 0.45 +
            domain_overlap * 0.20 +
            title_overlap * 0.35
        )

        overlap = max(0, overlap - fake_penalty)

        agent["overlap"] = round(overlap, 4)
        agent["overlap_details"] = {
            "link_overlap": round(link_overlap, 4),
            "domain_overlap": round(domain_overlap, 4),
            "title_overlap": round(title_overlap, 4),
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

        # behavior risk overrides passive DB risk
        if overlap < 0.5:
            risk = max(risk, 0.7)
        if overlap == 0:
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
    status = "passed" if score >= 0.60 else "suspicious"

    suspicious_agents = [
        agent["agent_id"]
        for agent in agent_sets
        if agent["overlap"] < 0.5
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
        "agent_overlaps": [
            {
                "agent_id": a["agent_id"],
                "overlap": a["overlap"],
                "base_weight": round(a["base_weight"], 4),
                "weight": round(a["weight"], 4),
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

