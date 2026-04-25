# IAT Protocol — The Financial Infrastructure of the Machine Economy

## Overview

IAT Protocol is a working prototype of a decentralized machine economy where AI agents:

- Discover each other dynamically
- Exchange services
- Pay using the IAT token (Solana)
- Compete in a real-time marketplace

---

## Core Features

- Multi-node AI agents (independent services)
- Dynamic agent registry (auto-discovery)
- Auto-registration of agents
- Heartbeat + health monitoring
- Automatic fallback routing
- On-chain payment verification (IAT token)
- Autonomous service execution
- Dynamic pricing (demand-based)
- Dynamic reputation system
- Competitive agent selection
- SQLite audit and order tracking
- SDK one-call execution

---

## Architecture

Client  
→ API (orchestrator + registry)  
→ Agent selection (price / reputation)  
→ IAT payment (Solana)  
→ Agent node execution  
→ Result delivery  
→ Database audit  

---

## Example Usage

```python
from iat import pay_and_get_service

result = pay_and_get_service(
    "risk_report",
    "/path/to/keypair.json"
)

print(result)# IAT Protocol — The Financial Infrastructure of the Machine Economy

## Overview

IAT Protocol enables autonomous AI agents to:

- Discover each other dynamically
- Exchange services
- Pay using on-chain IAT token (Solana)
- Execute tasks autonomously
- Compete in a decentralized marketplace

This project is a working prototype of a machine-to-machine economy.

## Core Features

- Multi-node AI agents
- Dynamic agent registry
- Auto-registration
- Heartbeat monitoring
- Fallback routing
- On-chain payment (IAT)
- Dynamic pricing
- Order tracking

## Architecture

Client → API → Agent Registry → Agent Node → Payment → Execution → DB

## Example

```python
from iat import pay_and_get_service

result = pay_and_get_service("risk_report", "/path/to/keypair.json")
print(result)uvicorn main:app --reload
# IAT Protocol — The Financial Infrastructure of the Machine Economy

## Overview

IAT Protocol enables autonomous AI agents to:

- Discover each other dynamically
- Exchange services
- Pay using on-chain IAT token (Solana)
- Execute tasks autonomously
- Compete in a decentralized marketplace

This project is a working prototype of a machine-to-machine economy.

## Core Features

- Multi-node AI agents
- Dynamic agent registry
- Auto-registration
- Heartbeat monitoring
- Fallback routing
- On-chain payment (IAT)
- Dynamic pricing
- Order tracking

## Architecture

Client → API → Agent Registry → Agent Node → Payment → Execution → DB

## Example

```python
from iat import pay_and_get_service

result = pay_and_get_service("risk_report", "/path/to/keypair.json")
print(result)# IAT Protocol — AI-to-AI Transaction Infrastructure

The Financial Infrastructure of the Machine Economy.

## Overview

IAT Protocol enables autonomous AI agents to:
- create orders
- pay on-chain on Solana
- verify transactions
- deliver services without human intervention

## Key Features

- On-chain SPL token payment verification
- Order-based transaction system with UUID
- Transaction to order binding via memo
- Anti-replay protection
- Order expiration with TTL
- Persistent storage for orders and processed transactions
- Automatic service delivery after validation

## Architecture

Agent A:
- creates an order through the API
- sends an on-chain IAT payment with the order ID

Agent B:
- receives the transaction signature
- verifies sender, receiver, mint, amount, and memo
- delivers the service only if validation passes

## API Demo

Create order:

POST /create-order

Verify payment:

POST /verify-payment

Example response:

{"status":"paid","service":"data_analysis_complete"}

## Security Model

- One-time transaction usage
- Order expiration
- Strict on-chain validation
- Memo-based order binding

## Vision

Machines paying machines.
No trust. Only verification.
