# IAT Protocol — On-Chain AI Transaction Prototype

IAT Protocol is building financial infrastructure for the machine economy.

## Current milestone

This prototype now demonstrates:

- a real on-chain IAT payment on Solana
- transaction signature verification
- transaction detail retrieval
- checks for:
  - sender
  - receiver
  - mint
  - amount
- automatic service delivery after payment verification

## Demo flow

1. Agent A sends a real IAT transaction on-chain
2. The transaction signature is verified
3. Transaction details are checked
4. Agent B detects the payment
5. Agent B automatically delivers the service

## Current files

- `shared_protocol.py` — shared protocol logic
- `agent_a_client.py` — local buyer/client logic
- `agent_b_server.py` — local seller/server logic
- `live_demo.py` — live on-chain demo
- `iat/onchain.py` — on-chain helpers and verification

## Current status

This repository demonstrates a working prototype of AI-to-AI financial interaction using a real Solana SPL token.

It is still a prototype, but it already proves the core idea:
AI agents can trigger, verify, and react to real blockchain payments.

## Next step

The next milestone is structured transaction parsing and stronger on-chain verification logic.