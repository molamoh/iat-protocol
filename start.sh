#!/bin/bash
uvicorn agent_b_api:app --host 0.0.0.0 --port $PORT
