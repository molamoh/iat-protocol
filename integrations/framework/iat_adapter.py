import os
from iat import pay_and_get_service


class IATProtocolAdapter:
    """
    Generic adapter for agent frameworks.

    Usage:
        adapter = IATProtocolAdapter()
        result = adapter.buy_service("risk_report")
    """

    def __init__(self, keypair_path=None):
        self.keypair_path = keypair_path or os.getenv("IAT_KEYPAIR_PATH")
        if not self.keypair_path:
            raise RuntimeError("Missing IAT_KEYPAIR_PATH environment variable")

    def buy_service(self, service: str):
        return pay_and_get_service(service, self.keypair_path)

    def buy_risk_report(self):
        return self.buy_service("risk_report")
