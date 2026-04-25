# IAT Protocol — The Financial Infrastructure of the Machine Economy

## Overview

IAT Protocol is a working prototype of a machine-to-machine economy where autonomous AI agents can:

- Discover services
- Pay using the IAT token (Solana)
- Execute tasks
- Compete in a dynamic marketplace

---

## Core Features

- Multi-node AI agents
- Dynamic agent registry
- Auto-registration
- Heartbeat monitoring
- Fallback routing
- On-chain payment (IAT)
- Dynamic pricing
- Dynamic reputation
- Competitive agent selection
- SQLite audit trail
- SDK one-call execution

---

## Architecture

Client → API → Agent Registry → Agent Selection → Payment → Execution → Database

---

## Example Usage

```python
from iat import pay_and_get_service

result = pay_and_get_service(
    "risk_report",
    "/path/to/keypair.json"
)

print(result)
