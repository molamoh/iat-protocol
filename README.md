# 🤖 IAT Protocol

### AI-to-AI Payments on Solana

**IAT enables autonomous AI agents to send and receive payments programmatically.**
Built on Solana, designed for developers, and focused on real-world machine-to-machine transactions.

---

## 🚀 TL;DR

* 💸 AI agents can **pay each other automatically**
* ⚡ Built on **Solana** for fast, low-cost transactions
* 🧠 Simple SDK for developers
* 🔧 Working prototype available

---

## 🧠 Why IAT?

AI agents are becoming capable of:

* calling APIs
* generating content
* making decisions

But they **cannot natively transact value**.

> IAT provides a simple payment layer for AI agents.

---

## ⚙️ What IAT Does (Today)

* Send tokens between agents
* Trigger actions after payment
* Integrate into simple AI workflows

---

## 🔥 Quick Demo (30 seconds)

### 1. Clone the repo

```bash
git clone https://github.com/molamoh/iat-protocol
cd iat-protocol
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Agent B (receiver)

```bash
python agent_b.py
```

### 4. Run Agent A (sender)

```bash
python agent_a.py
```

### ✅ Expected result

* Agent A sends payment
* Agent B detects it
* Agent B executes action

Example output:

```
[Agent A] Payment sent: 0.001 IAT
[Agent B] Payment received ✅
[Agent B] Executing service...
```

---

## 🧪 Example Code

```python
from iat import wallet

# Agent A
wallet.pay(to="agent_b_wallet", amount=0.001)

# Agent B
if wallet.payment_received():
    execute_service()
```

---

## 🏗️ Architecture (Current)

* Solana blockchain (settlement layer)
* IAT token (payment unit)
* Lightweight Python SDK (prototype)
* Off-chain agent logic

---

## 🧩 Use Cases

* 🤖 AI paying for API access
* 📊 Data marketplaces between agents
* ⚙️ Autonomous SaaS agents
* 🔁 Pay-per-task AI execution

---

## 💡 Why Not Just Use SOL or USDC?

IAT is designed for:

* microtransactions
* programmable agent logic
* ecosystem incentives

Future work may include:

* agent reputation
* usage-based pricing
* automated economic coordination

---

## 📊 Token Info

* Name: IA Transaction
* Symbol: IAT
* Supply: 21,000,000,000
* Network: Solana
* Mint authority: Disabled

---

## 🗺️ Roadmap

### 2026

* ✅ Token deployed
* ✅ Prototype SDK
* 🔜 Developer tools
* 🔜 First integrations

### 2027

* Agent-to-agent marketplaces
* Payment automation tools
* Early partnerships

---

## 👨‍💻 For Developers

We are building:

* SDK (Python first)
* simple APIs for agent payments
* developer-friendly tools

👉 Contributions welcome

---

## 🤝 For Investors & Partners

IAT is positioned at the intersection of:

* AI agents
* on-chain payments
* autonomous systems

We are currently:

* early-stage
* building core infrastructure
* looking for technical collaborators

---

## ⚠️ Disclaimer

This is an early-stage prototype.
Features are experimental and evolving.

---

## 📬 Contact

* GitHub: https://github.com/molamoh/iat-protocol
* More channels coming soon

---

## 🧠 Vision (Long-Term)

> AI agents will not just think.
> They will transact.

IAT aims to provide the financial rails for that future.

---
