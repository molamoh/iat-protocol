"""Seller-facing SDK built on the stable IAT transport."""

from __future__ import annotations

from typing import Any, Mapping

from iat.buyer import IATClient, RetryPolicy


class IATSellerClient(IATClient):
    """Evaluate, register, publish, and operate an IAT supplier."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        seller_api_key: str | None = None,
        timeout: float = 30.0,
        retry_policy: RetryPolicy | None = None,
        session=None,
    ):
        super().__init__(
            base_url,
            timeout=timeout,
            retry_policy=retry_policy,
            session=session,
            user_agent="iat-seller-python/1.0",
        )
        self.seller_api_key = seller_api_key

    @classmethod
    def from_env(cls, **overrides: Any) -> "IATSellerClient":
        import os

        return cls(
            base_url=overrides.pop("base_url", os.getenv("IAT_API_URL", "http://localhost:8000")),
            seller_api_key=overrides.pop("seller_api_key", os.getenv("IAT_SELLER_API_KEY")),
            **overrides,
        )

    def discover_seller_program(self) -> dict[str, Any]:
        return self._request("GET", "/seller/v1/discovery")

    def assess_readiness(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/seller/v1/readiness", json=dict(profile))

    def estimate_economics(
        self,
        *,
        unit_price: str | int | float,
        monthly_completed_orders: int,
        refund_rate: str | int | float = "0",
        variable_cost_per_order: str | int | float = "0",
        commission_rate: str | int | float | None = None,
    ) -> dict[str, Any]:
        payload = {
            "unit_price": str(unit_price),
            "monthly_completed_orders": monthly_completed_orders,
            "refund_rate": str(refund_rate),
            "variable_cost_per_order": str(variable_cost_per_order),
            "commission_rate": None if commission_rate is None else str(commission_rate),
        }
        return self._request("POST", "/seller/v1/economics/estimate", json=payload)

    def integration_contract(self, runtime_adapter: str = "http") -> dict[str, Any]:
        return self._request(
            "GET",
            "/seller/v1/integration-contract",
            params={"runtime_adapter": runtime_adapter},
        )

    def register(
        self,
        *,
        seller_name: str,
        wallet: str,
        email: str,
        organization_name: str | None = None,
        website: str | None = None,
        support_email: str | None = None,
        webhook_url: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/seller/register",
            json={
                "seller_name": seller_name,
                "wallet": wallet,
                "email": email,
                "organization_name": organization_name,
                "website": website,
                "support_email": support_email,
                "webhook_url": webhook_url,
                "metadata": dict(metadata or {}),
            },
        )

    def register_agent(
        self,
        *,
        agent_id: str,
        service: str,
        runtime_adapter: str = "http",
        url: str | None = None,
        wallet: str | None = None,
        price: float = 1.0,
        capabilities: list[str] | None = None,
        specialties: list[str] | None = None,
        python_plugin: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._seller_request(
            "POST",
            "/seller/register-agent",
            json={
                "agent_id": agent_id,
                "service": service,
                "runtime_adapter": runtime_adapter,
                "url": url,
                "wallet": wallet,
                "price": price,
                "capabilities": list(capabilities or []),
                "specialties": list(specialties or []),
                "python_plugin": python_plugin,
                "metadata": dict(metadata or {}),
            },
        )

    def dashboard(self) -> dict[str, Any]:
        return self._seller_request("GET", "/seller/dashboard")

    def analytics(self) -> dict[str, Any]:
        return self._seller_request("GET", "/seller/analytics")

    def payouts(self) -> dict[str, Any]:
        return self._seller_request("GET", "/seller/payouts")

    def create_catalog_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        return self._seller_request("POST", "/seller/catalog/items", json=dict(item))

    def _seller_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.seller_api_key:
            raise ValueError("seller_api_key is required for this operation")
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["x-seller-api-key"] = self.seller_api_key
        return self._request(method, path, headers=headers, **kwargs)
