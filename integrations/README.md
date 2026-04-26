# IAT Protocol Integrations

This folder contains adapters that allow open-source AI agent frameworks to use IAT Protocol as an economic execution layer.

## Available Integrations

- CrewAI
- LangChain
- AutoGPT
- OpenAgents

## Security

Never hardcode private wallet paths in public code.

Use an environment variable:

export IAT_KEYPAIR_PATH="/secure/path/to/keypair.json"

## Concept

Agents can use IAT as a tool to:

1. Discover a service
2. Pay with IAT
3. Verify payment on-chain
4. Receive the result
5. Continue reasoning
