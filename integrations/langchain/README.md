# IAT Protocol for LangChain

This integration exposes IAT Protocol as a LangChain tool.

## Usage

```python
from integrations.langchain.iat_tool import iat_pay_and_get_service

result = iat_pay_and_get_service.invoke("risk_report")
print(result)
```

Required environment:

```bash
export IAT_API_URL="http://127.0.0.1:8000"
export IAT_KEYPAIR_PATH="/run/secrets/buyer-keypair.json"
```

Invocation performs a real payment when the configured API returns a payable
order.
