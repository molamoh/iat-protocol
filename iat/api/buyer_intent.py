import os
import json
import requests


def fallback_intent(prompt: str):
    return {
        "provider": "fallback_rules",
        "protocol_language": "en",
        "purchase_type": "general_research",
        "goal": prompt,
        "requirements": {},
        "missing_requirements": ["topic", "depth", "deadline"],
        "questions": [
            "What exact topic should be researched?",
            "Do you want a quick summary or a deep report?",
            "When do you need the result?"
        ],
        "confidence": 0.50,
    }


def normalize_buyer_intent(prompt: str):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return fallback_intent(prompt)

    system_prompt = """
You are the Buyer Intent Engine for IAT Protocol.

Your role:
- deeply understand buyer intent
- extract structured requirements
- detect missing information
- ask intelligent follow-up questions
- maximize value-for-money recommendations

Rules:
- Always return valid JSON only.
- Default protocol language is English.
- Never expose protocol internals.
- Be strict before declaring that requirements are complete.
- If important information is missing, include it in missing_requirements.
- Questions should help optimize recommendation quality, not just technical completion.
- Think like a world-class shopping assistant.

Examples of important missing info:
- budget
- country/location
- usage
- urgency
- preferred brands
- quality expectations
- compatibility requirements
- constraints

Completion rule:
For product purchase intents, do not return an empty missing_requirements list unless at least these are known:
- budget or price range
- country/location
- intended usage
- main priorities
If any of these are missing, ask concise follow-up questions.
"""

    user_prompt = f"""
Buyer prompt:
{prompt}

Return JSON with this exact shape:
{{
  "provider": "groq",
  "protocol_language": "en",
  "purchase_type": "",
  "goal": "",
  "requirements": {{}},
  "missing_requirements": [],
  "questions": [],
  "confidence": 0.0
}}
"""

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
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=20,
        )

        if r.status_code != 200:
            return fallback_intent(prompt)

        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    except Exception:
        return fallback_intent(prompt)
