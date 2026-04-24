# IAT Protocol — AI-to-AI Transaction Infrastructure

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
