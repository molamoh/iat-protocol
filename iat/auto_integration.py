import os
import requests

from iat.sdk import pay_and_get_service


class IATMarket:
    def __init__(self, keypair_path=None):
        self.keypair_path = keypair_path or os.getenv("IAT_KEYPAIR_PATH")

    def buy(self, service, query=None):
        return pay_and_get_service(service, self.keypair_path, query=query)

    def request(self, query, service="web_research", max_price=999999, priority="quality"):
        api = os.getenv("IAT_API_URL", "http://localhost:8000")

        preview = requests.post(
            f"{api}/intent-preview",
            json={
                "service": service,
                "query": query,
                "max_price": max_price,
                "priority": priority,
            },
            timeout=90,
        ).json()

        if preview.get("status") != "ok":
            return {
                "status": "intent_failed",
                "preview": preview,
            }

        execution = self.buy(service, query=query)

        return {
            "status": execution.get("status"),
            "intent": preview.get("intent"),
            "selected_bids": preview.get("selected"),
            "execution": execution,
        }


def enable_ai_market(keypair_path=None):
    return IATMarket(keypair_path=keypair_path)


# Backward compatibility aliases
IATEconomicTool = IATMarket

def enable_iat_economy(keypair_path=None):
    return IATMarket(keypair_path=keypair_path)
