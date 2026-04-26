# IAT Protocol for LangChain

This integration exposes IAT Protocol as a LangChain tool.

## Usage

from integrations.langchain.iat_tool import iat_pay_and_get_service

result = iat_pay_and_get_service.invoke("risk_report")
print(result)
