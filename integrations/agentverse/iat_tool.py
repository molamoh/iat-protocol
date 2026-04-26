import os
from iat import pay_and_get_service


class IATAgentVerseTool:
    """
    AgentVerse-style tool interface for IAT Protocol.
    """

    name = "iat_pay_and_get_service"
    description = "Buy an external agent service using IAT Protocol."

    def __init__(self, keypair_path=None):
        self.keypair_path = keypair_path or os.getenv("IAT_KEYPAIR_PATH")

    def run(self, service: str):
        if not self.keypair_path:
            return {
                "status": "error",
                "message": "Missing IAT_KEYPAIR_PATH environment variable"
            }

        return pay_and_get_service(service, self.keypair_path)
