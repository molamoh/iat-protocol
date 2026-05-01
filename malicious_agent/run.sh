#!/bin/bash

export IAT_REGISTRY_URL="${IAT_REGISTRY_URL:-https://iat-protocol.onrender.com}"
export IAT_AGENT_PUBLIC_URL="${IAT_AGENT_PUBLIC_URL:-http://localhost:9000}"
export IAT_AGENT_ID="${IAT_AGENT_ID:-my_agent}"
export IAT_SERVICE="${IAT_SERVICE:-my_service}"
export IAT_AGENT_WALLET="${IAT_AGENT_WALLET:-YOUR_WALLET}"
export IAT_PRICE="${IAT_PRICE:-1.0}"
export IAT_REPUTATION="${IAT_REPUTATION:-0.8}"

uvicorn app:app --host 0.0.0.0 --port "${PORT:-9000}"
