# IAT Protocol — AI to AI On-Chain Transactions

IAT Protocol is building financial infrastructure for the machine economy.

## 🚀 Current Milestone (B5)

This prototype demonstrates a **complete AI-to-AI on-chain payment validation flow on Solana**.

### What works today

- Real SPL token transaction (IAT)
- Transaction signature verification
- Transaction detail parsing
- Full validation:
  - Sender verification
  - Receiver verification
  - Token (mint) verification
  - Amount verification
- Automatic service delivery by another AI agent

## 🔁 Flow

1. Agent A sends an on-chain IAT payment
2. Transaction signature is verified
3. Transaction is parsed and validated
4. Agent B confirms the payment
5. Agent B automatically delivers the service

➡️ No human intervention

## 📁 Project Structure

- `agent_a_client.py` — buyer agent
- `agent_b_server.py` — seller agent API
- `live_demo.py` — on-chain demo
- `iat/onchain.py` — blockchain verification logic
- `shared_protocol.py` — core logic

## 🧠 Why this matters

This prototype proves that:

> AI agents can trigger, verify, and react to real blockchain payments autonomously.

This is a first step toward a **machine-native financial layer**.

## ⚠️ Status

This is an early prototype.

Next steps:
- stronger transaction parsing (structured, no string fallback)
- protocol standardization
- multi-agent coordination