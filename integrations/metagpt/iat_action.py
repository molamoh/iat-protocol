import os
from iat import pay_and_get_service


class IATBuyServiceAction:
    """
    MetaGPT-style action.

    This action allows a MetaGPT role/agent to buy an external service
    through IAT Protocol.
    """

    name = "iat_buy_service"

    def __init__(self, keypair_path=None):
        self.keypair_path = keypair_path or os.getenv("IAT_KEYPAIR_PATH")

    async def run(self, service: str = "risk_report"):
        if not self.keypair_path:
            return {
                "status": "error",
                "message": "Missing IAT_KEYPAIR_PATH environment variable"
            }

        return pay_and_get_service(service, self.keypair_path)
