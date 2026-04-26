import os
from iat import pay_and_get_service


class IATEconomicTool:
    name = "iat_pay_and_get_service"
    description = (
        "Buy an external AI service through IAT Protocol, pay with IAT token, "
        "verify payment on-chain, and return the delivered result."
    )

    def __init__(self, keypair_path=None):
        self.keypair_path = keypair_path or os.getenv("IAT_KEYPAIR_PATH")

        if not self.keypair_path:
            raise RuntimeError("Missing IAT_KEYPAIR_PATH environment variable")

    def run(self, service: str = "risk_report"):
        return pay_and_get_service(service, self.keypair_path)

    def __call__(self, service: str = "risk_report"):
        return self.run(service)


def enable_iat_economy(agent=None, keypair_path=None):
    """
    Universal IAT economic layer.

    If agent is provided and has a `tools` attribute, IAT is injected as a tool.
    If no agent is provided, returns a standalone IAT economic tool.
    """
    tool = IATEconomicTool(keypair_path=keypair_path)

    if agent is not None:
        if hasattr(agent, "tools"):
            agent.tools.append(tool)
            return agent

        if isinstance(agent, dict):
            agent.setdefault("tools", []).append(tool)
            return agent

    return tool
