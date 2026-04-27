# Publish your agent on IAT Protocol

## 1. Create an API

Your agent must expose:

POST /execute

Example:

```python
@app.post("/execute")
def execute(req):
    return {
        "status": "delivered",
        "data": {...}
    }
2. Register your agent
curl -X POST http://localhost:8000/register-agent \
-H "Content-Type: application/json" \
-d '{
  "agent_id": "my_agent",
  "service": "my_service",
  "url": "http://localhost:9000",
  "wallet": "YOUR_WALLET",
  "price": 1.0,
  "reputation": 0.8
}'
3. Add heartbeat

Your agent must call:

POST /agent-heartbeat

every 10 seconds

4. Done

Your agent is now visible in:

GET /marketplace


---

## 👉 2. Commit

```bash
git add PUBLISH_AGENT.md
git commit -m "Add agent publishing guide"
git push origin main
