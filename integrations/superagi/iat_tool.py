import os
from iat import pay_and_get_service


class IATSuperAGITool:
    """
    SuperAGI-style tool skeleton.

    SuperAGI uses Toolkits/custom tools. This class provides the core
    execution logic that can be wrapped into a SuperAGI Toolkit.
    """

    name = "iat_pay_and_get_service"
    description = "Buy an IAT Protocol service, pay on-chain, and return result."

    def execute(self, service: str):
        keypair_path = os.getenv("IAT_KEYPAIR_PATH")

        if not keypair_path:
            return {
                "status": "error",
                "message": "Missing IAT_KEYPAIR_PATH environment variable"
            }

        return pay_and_get_service(service, keypair_path)
