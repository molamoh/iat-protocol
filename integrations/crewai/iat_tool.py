import os
from typing import Type
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from iat import pay_and_get_service


class IATServiceInput(BaseModel):
    service: str = Field(..., description="IAT service name, for example risk_report")


class IATPayAndGetServiceTool(BaseTool):
    name: str = "iat_pay_and_get_service"
    description: str = (
        "Buy a service from the IAT Protocol marketplace, pay with IAT token, "
        "verify payment on-chain, and return the delivered result."
    )
    args_schema: Type[BaseModel] = IATServiceInput

    def _run(self, service: str):
        keypair_path = os.getenv("IAT_KEYPAIR_PATH")
        if not keypair_path:
            return {"status": "error", "message": "Missing IAT_KEYPAIR_PATH"}
        return pay_and_get_service(service, keypair_path)
