import os
from langchain.tools import tool
from iat import pay_and_get_service


@tool("iat_pay_and_get_service")
def iat_pay_and_get_service(service: str):
    """
    Buy a service from the IAT Protocol marketplace, pay with IAT token,
    verify payment on-chain, and return the delivered result.
    """
    keypair_path = os.getenv("IAT_KEYPAIR_PATH")
    if not keypair_path:
        return {"status": "error", "message": "Missing IAT_KEYPAIR_PATH"}
    return pay_and_get_service(service, keypair_path)
