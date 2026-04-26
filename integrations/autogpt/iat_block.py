import os
from iat import pay_and_get_service


def iat_pay_and_get_service_block(service: str):
    """
    AutoGPT-style reusable block.

    Input:
        service: IAT marketplace service name

    Output:
        IAT execution result
    """
    keypair_path = os.getenv("IAT_KEYPAIR_PATH")

    if not keypair_path:
        return {
            "status": "error",
            "message": "Missing IAT_KEYPAIR_PATH environment variable"
        }

    return pay_and_get_service(service, keypair_path)
