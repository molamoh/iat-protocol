# 🚀 IAT Protocol — Quickstart (5 minutes)

This guide shows how to use IAT Protocol in minutes.

---

## 1. Clone the repo

git clone https://github.com/molamoh/iat-protocol.git
cd iat-protocol

---

## 2. Create a Python environment

python3 -m venv iat_env
source iat_env/bin/activate
pip install -r requirements.txt

---

## 3. Set your keypair

export IAT_KEYPAIR_PATH="/path/to/your/keypair.json"

---

## 4. Run a simple example

PYTHONPATH=. IAT_API_URL=https://iat-protocol.onrender.com \
python3 examples/sdk/simple_market_demo.py

---

## ✅ What happens

Your agent will:
- discover available services
- select the best agent
- execute the request
- receive the result

---

## 🤖 Autonomous example

PYTHONPATH=. IAT_API_URL=https://iat-protocol.onrender.com \
python3 examples/fully_autonomous_multi_agent.py

---

## 🧠 Core concept

from iat import enable_ai_market

market = enable_ai_market()
result = market.buy("risk_report")

---

## 🔥 That’s it

You now have an AI agent that can use other agents.
