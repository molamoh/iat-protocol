import os
from iat import pay_and_get_service


class IATMarket:
    """
    Universal AI agent marketplace client.

    Example:
        from iat import enable_ai_market

        market = enable_ai_market()
        result = market.buy("risk_report")
    """

    name = "iat_ai_market"
    description = (
        "Buy external AI services through IAT Protocol, pay with IAT token, "
        "verify payment on-chain, and return delivered results."
    )

    def __init__(self, keypair_path=None):
        self.keypair_path = keypair_path or os.getenv("IAT_KEYPAIR_PATH")

        if not self.keypair_path:
            raise RuntimeError("Missing IAT_KEYPAIR_PATH environment variable")

    def buy(self, service: str = "risk_report", query=None):
        return pay_and_get_service(service, self.keypair_path, query=query)

    def run(self, service: str = "risk_report", query=None):
        return self.buy(service, query=query)

    def __call__(self, service: str = "risk_report", query=None):
        return self.buy(service, query=query)


# Backward-compatible alias
IATEconomicTool = IATMarket


def enable_ai_market(agent=None, keypair_path=None):
    """
    Enable IAT Protocol as an AI marketplace layer.

    If an agent object has a `tools` attribute, the IAT market client is injected.
    Otherwise, returns a standalone market client.
    """
    market = IATMarket(keypair_path=keypair_path)

    if agent is not None:
        if hasattr(agent, "tools"):
            agent.tools.append(market)
            return agent

        if isinstance(agent, dict):
            agent.setdefault("tools", []).append(market)
            return agent

    return market


# Backward-compatible alias
def enable_iat_economy(agent=None, keypair_path=None):
    return enable_ai_market(agent=agent, keypair_path=keypair_path)
