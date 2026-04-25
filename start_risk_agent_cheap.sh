#!/bin/bash
uvicorn nodes.risk_agent_node.app:app --host 0.0.0.0 --port $PORT
