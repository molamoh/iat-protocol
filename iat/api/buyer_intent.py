import os
import json
import requests

from iat.api.groq_config import GROQ_CHAT_COMPLETIONS_URL, groq_json_request


def fallback_intent(prompt: str):
    return {
        "provider": "fallback_rules",
        "protocol_language": "en",
        "purchase_type": "general_research",
        "goal": prompt,
        "requirements": {
            "topic": prompt
        } if prompt else {},
        "missing_requirements": [],
        "questions": [],
        "required_capabilities": [
            "web_search",
            "buyer_research"
        ],
        "preferred_specialties": [
            "general_web"
        ],
        "output_mode": "buyer_friendly",
        "urgency": "normal",
        "quality_preference": "balanced",
        "execution_strategy": "balanced",
        "trust_preference": "foundation_allowed",
        "consensus_preference": "standard",
        "max_latency_preference": "normal",
        "confidence": 0.50,
    }


def normalize_buyer_intent(prompt: str, previous_context: dict | None = None):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return fallback_intent(prompt)

    previous_context = previous_context or {}

    system_prompt = """
You are the Buyer Intent Engine for IAT Protocol.

IAT Protocol is infrastructure for AI-to-AI economic transactions.
A buyer can be a human or an AI agent.
Your job is to transform a natural language request into a structured machine-commerce intent.

Core principles:
- The protocol must remain generic.
- Do NOT hardcode vertical business logic.
- Do NOT expose protocol internals to the buyer.
- Understand what the buyer wants.
- Extract requirements.
- Decide if clarification is truly needed.
- Suggest required capabilities and preferred specialties.
- Infer execution strategy: cheapest, balanced, premium, fastest, safest, consensus_required.
- Infer trust preference: foundation_only, foundation_allowed, open_market.
- Infer consensus preference: none, standard, strict.
- Keep the result usable for autonomous agent routing.
- Ask questions only when missing information would materially affect execution quality.
- If the request is actionable enough, do NOT over-clarify.

Important:
- service routing is handled later by IAT.
- You should output capabilities and specialties, not choose a concrete agent.
- Buyer should never see agent URLs, wallets, registry mechanics, scoring, staking, or consensus internals.

Clarification policy:
Ask clarification only if the request cannot be executed responsibly.
For research, analysis, summarization, comparison, monitoring, or web search:
- If topic is clear, do not ask for topic again.
- If urgency is implied by words like "today", "now", "current", "latest", set urgency accordingly.
- If depth is implied by words like "deep", "detailed", "quick", set quality/depth accordingly.
- If enough information exists for a useful first result, missing_requirements must be [].

Capabilities examples:
- web_search
- buyer_research
- market_research
- risk_analysis
- price_comparison
- product_research
- travel_research
- finance_research
- crypto_research
- legal_research
- technical_research
- data_analysis
- summarization
- monitoring

Specialties examples:
- general_web
- deep_research
- market_analysis
- risk
- finance
- crypto
- bitcoin
- consumer_products
- shopping_research
- travel
- hotels
- software
- business
- legal
- technical

Return valid JSON only.
"""

    user_prompt = f"""
Buyer prompt:
{prompt}

Previous context, if any:
{json.dumps(previous_context, ensure_ascii=False)}

Return JSON with this exact shape:
{{
  "provider": "groq",
  "protocol_language": "en",
  "purchase_type": "",
  "goal": "",
  "requirements": {{}},
  "missing_requirements": [],
  "questions": [],
  "required_capabilities": [],
  "preferred_specialties": [],
  "output_mode": "buyer_friendly",
  "urgency": "normal",
  "quality_preference": "balanced",
  "execution_strategy": "balanced",
  "trust_preference": "foundation_allowed",
  "consensus_preference": "standard",
  "max_latency_preference": "normal",
  "confidence": 0.0
}}
"""

    try:
        r = requests.post(
            GROQ_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=groq_json_request(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            ),
            timeout=20,
        )

        if r.status_code != 200:
            return fallback_intent(prompt)

        content = r.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        # Safety normalization: guarantee required keys exist.
        base = fallback_intent(prompt)
        base.update(parsed)

        if not isinstance(base.get("requirements"), dict):
            base["requirements"] = {}

        if not isinstance(base.get("missing_requirements"), list):
            base["missing_requirements"] = []

        if not isinstance(base.get("questions"), list):
            base["questions"] = []

        if not isinstance(base.get("required_capabilities"), list):
            base["required_capabilities"] = []

        if not isinstance(base.get("preferred_specialties"), list):
            base["preferred_specialties"] = []

        allowed_strategies = {"cheapest", "balanced", "premium", "fastest", "safest", "consensus_required"}
        if base.get("execution_strategy") not in allowed_strategies:
            base["execution_strategy"] = "balanced"

        allowed_trust = {"foundation_only", "foundation_allowed", "open_market"}
        if base.get("trust_preference") not in allowed_trust:
            base["trust_preference"] = "foundation_allowed"

        allowed_consensus = {"none", "standard", "strict"}
        if base.get("consensus_preference") not in allowed_consensus:
            base["consensus_preference"] = "standard"

        allowed_latency = {"normal", "fast", "urgent"}
        if base.get("max_latency_preference") not in allowed_latency:
            base["max_latency_preference"] = "normal"

        if not base.get("purchase_type"):
            base["purchase_type"] = "general_research"

        try:
            confidence = float(base.get("confidence", 0) or 0)
        except Exception:
            confidence = 0

        if confidence <= 0:
            base["confidence"] = 0.75

        prompt_l = str(prompt or "").lower().strip()
        goal_l = str(base.get("goal") or "").lower().strip()

        vague_phrases = [
            "find me the best option",
            "best option",
            "help me choose",
            "what should i buy",
            "find something",
            "i need something",
        ]

        too_vague = (
            prompt_l in vague_phrases
            or goal_l in vague_phrases
            or len(prompt_l.split()) <= 4
        )

        if too_vague:
            base["missing_requirements"] = ["objective", "category", "constraints"]
            base["questions"] = [
                "What exactly do you want to find or decide?",
                "What category or topic should this be about?",
                "Do you have any budget, location, quality, timing, or other constraints?"
            ]
            base["requirements"] = {}
            base["confidence"] = min(float(base.get("confidence", 0.75)), 0.45)

        return base

    except Exception:
        return fallback_intent(prompt)


def merge_buyer_intent_with_session(previous_session: dict | None, new_intent: dict, new_prompt: str):
    """
    Merge previous buyer session memory with the new Groq-normalized intent.

    This keeps IAT generic:
    - no hardcoded vertical business logic
    - requirements are accumulated dynamically
    - Groq remains the intelligence layer
    """
    previous_session = previous_session or {}
    new_intent = new_intent or {}

    previous_requirements = previous_session.get("requirements") or {}
    new_requirements = new_intent.get("requirements") or {}

    merged_requirements = dict(previous_requirements)

    for k, v in new_requirements.items():
        if v is not None and v != "":
            merged_requirements[k] = v

    prompt_l = str(new_prompt or "").lower()

    # Generic lightweight enrichment from the latest buyer message.
    # This does not choose agents; it only preserves buyer constraints.
    focus_terms = []
    for term in [
        "liquidity",
        "risk",
        "volatility",
        "sentiment",
        "technical",
        "macro",
        "on-chain",
        "onchain",
        "liquidation",
    ]:
        if term in prompt_l:
            focus_terms.append(term)

    if focus_terms:
        existing_focus = merged_requirements.get("focus") or []
        if not isinstance(existing_focus, list):
            existing_focus = [str(existing_focus)]

        for term in focus_terms:
            if term not in existing_focus:
                existing_focus.append(term)

        merged_requirements["focus"] = existing_focus

    if any(w in prompt_l for w in ["today", "now", "asap", "latest", "current"]):
        merged_requirements["deadline"] = "today"

    if "max price" in prompt_l or "budget" in prompt_l:
        import re
        prices = re.findall(r"(\d+(?:\.\d+)?)\s*(iat|usd|eur|€|\$)?", prompt_l)
        if prices:
            merged_requirements["max_price"] = float(prices[0][0])

    previous_messages = previous_session.get("messages") or []

    new_message = {
        "role": "buyer",
        "content": new_prompt,
    }

    if not previous_messages or previous_messages[-1].get("content") != new_prompt:
        previous_messages.append(new_message)

    merged = dict(new_intent)
    merged["requirements"] = merged_requirements
    merged["messages"] = previous_messages[-10:]

    if not merged.get("goal"):
        merged["goal"] = previous_session.get("goal") or new_prompt

    if not merged.get("purchase_type"):
        merged["purchase_type"] = previous_session.get("purchase_type") or "general_research"

    previous_capabilities = previous_session.get("required_capabilities") or []
    new_capabilities = merged.get("required_capabilities") or []

    merged["required_capabilities"] = list(dict.fromkeys(
        list(previous_capabilities) + list(new_capabilities)
    ))

    previous_specialties = previous_session.get("preferred_specialties") or []
    new_specialties = merged.get("preferred_specialties") or []

    merged["preferred_specialties"] = list(dict.fromkeys(
        list(previous_specialties) + list(new_specialties)
    ))

    # Lightweight capability enrichment from accumulated requirements.
    focus = merged_requirements.get("focus") or []
    if not isinstance(focus, list):
        focus = [str(focus)]

    focus_l = " ".join(focus).lower()

    if "risk" in focus_l and "risk_analysis" not in merged["required_capabilities"]:
        merged["required_capabilities"].append("risk_analysis")

    if "liquidity" in focus_l and "market_research" not in merged["required_capabilities"]:
        merged["required_capabilities"].append("market_research")

    if "risk" in focus_l and "risk" not in merged["preferred_specialties"]:
        merged["preferred_specialties"].append("risk")

    if "liquidity" in focus_l and "market_analysis" not in merged["preferred_specialties"]:
        merged["preferred_specialties"].append("market_analysis")

    return merged

def analyze_seller_risk_with_groq(seller_profile: dict):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return {
            "provider": "fallback",
            "seller_risk_level": "unknown",
            "risk_score": 0.5,
            "recommended_action": "manual_review",
            "reasons": ["Groq unavailable"],
            "red_flags": [],
            "missing_evidence": [],
            "confidence": 0.1,
        }

    system_prompt = """
You are the Seller Risk Analysis Engine for IAT Protocol.

Your role:
- Analyze whether a newly registered seller appears trustworthy, suspicious, fraudulent, unrealistic, or high-risk.
- You are NOT the final authority.
- You only produce a risk advisory for the protocol foundation layer.

Analyze:
- Seller claims
- Business consistency
- Wallet legitimacy signals
- URL/domain quality
- Product realism
- Proof links quality
- Refund policy realism
- Pricing realism
- Fraud indicators
- Escrow-like behavior
- Potential scam patterns
- Potential impersonation
- High-risk wording
- Missing operational evidence

Rules:
- Be skeptical.
- Prefer caution over optimism.
- Never auto-approve.
- Flag exaggerated claims.
- Flag unrealistic pricing.
- Flag suspicious wording.
- Flag weak evidence.
- If evidence is insufficient, recommend manual review.
- If multiple strong red flags exist, recommend reject.

Return JSON only.

JSON format:
{
  "provider": "groq",
  "seller_risk_level": "low|medium|high",
  "risk_score": 0.0,
  "recommended_action": "approve|manual_review|reject",
  "reasons": [],
  "red_flags": [],
  "missing_evidence": [],
  "confidence": 0.0
}
"""

    user_prompt = json.dumps(
        seller_profile,
        ensure_ascii=False,
        indent=2
    )

    try:
        r = requests.post(
            GROQ_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=groq_json_request(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            ),
            timeout=30,
        )

        if r.status_code != 200:
            return {
                "provider": "fallback",
                "seller_risk_level": "unknown",
                "risk_score": 0.5,
                "recommended_action": "manual_review",
                "reasons": [f"Groq HTTP {r.status_code}"],
                "red_flags": [],
                "missing_evidence": [],
                "confidence": 0.1,
            }

        parsed = json.loads(
            r.json()["choices"][0]["message"]["content"]
        )

        return parsed

    except Exception as e:
        return {
            "provider": "fallback",
            "seller_risk_level": "unknown",
            "risk_score": 0.5,
            "recommended_action": "manual_review",
            "reasons": [str(e)],
            "red_flags": [],
            "missing_evidence": [],
            "confidence": 0.1,
        }


def forecast_seller_attack_vectors_with_groq(threat_context: dict):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return {
            "provider": "fallback",
            "threat_level": "unknown",
            "predicted_attack_vectors": [],
            "recommended_guardrails": [],
            "confidence": 0.1,
        }

    system_prompt = """
You are the Adversarial Threat Forecasting Engine for IAT Protocol.

IAT is an AI-to-AI machine commerce protocol.
Your task is to forecast possible future attacks before they happen.

You are advisory only.
The protocol/foundation layer makes final decisions.

Analyze:
- seller behavior
- graph relationships
- fingerprints
- economic exposure
- velocity patterns
- consensus divergence
- rehabilitation cycles
- risk decay patterns
- potential Sybil strategies
- AI-agent manipulation strategies
- reputation farming
- delayed fraud / rug-pull preparation
- prompt manipulation
- proof forgery
- marketplace flooding
- fake honest volume
- coordinated seller clusters

Return JSON only:
{
  "provider": "groq",
  "threat_level": "low|medium|high|critical",
  "predicted_attack_vectors": [],
  "recommended_guardrails": [],
  "signals_to_monitor": [],
  "policy_updates": [],
  "confidence": 0.0
}
"""

    try:
        r = requests.post(
            GROQ_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=groq_json_request(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            threat_context,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    },
                ],
                temperature=0.2,
            ),
            timeout=30,
        )

        if r.status_code != 200:
            return {
                "provider": "fallback",
                "threat_level": "unknown",
                "predicted_attack_vectors": [],
                "recommended_guardrails": [],
                "signals_to_monitor": [],
                "policy_updates": [],
                "confidence": 0.1,
            }

        return json.loads(r.json()["choices"][0]["message"]["content"])

    except Exception as e:
        return {
            "provider": "fallback",
            "threat_level": "unknown",
            "predicted_attack_vectors": [],
            "recommended_guardrails": [],
            "signals_to_monitor": [],
            "policy_updates": [],
            "error": str(e),
            "confidence": 0.1,
        }
