import os
from integrations.crewai.iat_tool import IATPayAndGetServiceTool

if not os.getenv("IAT_KEYPAIR_PATH"):
    raise RuntimeError("Missing IAT_KEYPAIR_PATH")

tool = IATPayAndGetServiceTool()

result = tool._run("risk_report")

print("=== IAT CREWAI TOOL DIRECT TEST ===")
print(result)
