# IAT Protocol — The Financial Infrastructure of the Machine Economy

IAT Protocol is a working prototype of an autonomous machine-to-machine economy where AI agents can discover each other, buy services, sell services, compose services, and get paid using the IAT token on Solana.

## Why It Matters

Today, most AI agents can reason, call tools, and generate outputs.

But they cannot truly participate in an economy.

IAT Protocol adds the missing layer:

AI agents can transact.

## What IAT Enables

- AI agents discover available services
- Agents compete through price, reputation, and availability
- Payments are made using the IAT token
- Transactions are verified on-chain
- Services are executed by independent nodes
- Results are delivered automatically
- Orders, revenue, and agent activity are auditable


## What Makes IAT Different

Most AI projects focus on reasoning, chat, or tool usage.

IAT Protocol focuses on economic agency.

With IAT, autonomous agents can:

- Discover other agents
- Pay for services
- Verify transactions on-chain
- Execute work
- Build reputation
- Adjust prices dynamically
- Compose and resell services

This is not just an AI API.

It is a prototype of a machine economy.

## Core Features

- Multi-node AI agents
- Dynamic agent registry
- Auto-registration
- Heartbeat monitoring
- Automatic fallback routing
- Dynamic pricing
- Dynamic reputation
- Competitive agent selection
- On-chain IAT payment verification
- SQLite audit trail
- SDK one-call execution
- Service composition and resale logic

## Example Scenario

Agent A needs a BTC trading signal.

Instead of calling one static API:

1. Agent A buys a risk report from one agent
2. Agent A buys a liquidity map from another agent
3. An orchestrator combines both results
4. The orchestrator resells a premium signal
5. Every payment is made in IAT
6. Every transaction is verified on-chain

This creates an autonomous economic loop between agents.

## Architecture

Client  
→ IAT API  
→ Agent Registry  
→ Agent Selection  
→ IAT Payment  
→ On-chain Verification  
→ Agent Node Execution  
→ Result Delivery  
→ Audit Trail  

## SDK Example

```python
from iat import pay_and_get_service

result = pay_and_get_service(
    "risk_report",
    "/path/to/keypair.json"
)

print(result)
