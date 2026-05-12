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
Always return valid JSON only.
Default protocol language is English.
Extract the buyer goal, purchase type, known requirements, missing requirements, clarification questions, and confidence.
Never expose protocol internals.
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
