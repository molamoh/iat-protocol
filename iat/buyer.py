"""Production-quality synchronous buyer client for humans and AI agents."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

import requests


class IATClientError(RuntimeError):
    """Base client error with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        details: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "error",
            "code": self.code,
            "message": str(self),
            "http_status": self.status_code,
            "details": self.details,
        }


class IATTransportError(IATClientError):
    """The server could not be reached after bounded retries."""


class IATAPIError(IATClientError):
    """The server returned a non-success response."""


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    initial_delay: float = 0.25
    maximum_delay: float = 2.0
    retry_statuses: tuple[int, ...] = (429, 502, 503, 504)

    def __post_init__(self):
        if not 1 <= self.attempts <= 10:
            raise ValueError("retry attempts must be between 1 and 10")
        if self.initial_delay < 0 or self.maximum_delay < self.initial_delay:
            raise ValueError("invalid retry delay bounds")


class IATClient:
    """Typed entry point for discovery, sandbox evaluation, and buyer orders."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        retry_policy: RetryPolicy | None = None,
        session: requests.Session | None = None,
        user_agent: str = "iat-python/1.0",
    ):
        parsed = urlparse(str(base_url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if timeout <= 0 or timeout > 300:
            raise ValueError("timeout must be greater than zero and at most 300 seconds")
        self.base_url = str(base_url).rstrip("/") + "/"
        self.api_key = api_key
        self.timeout = float(timeout)
        self.retry_policy = retry_policy or RetryPolicy()
        self.session = session or requests.Session()
        self.user_agent = user_agent

    @classmethod
    def from_env(cls, **overrides: Any) -> "IATClient":
        import os

        return cls(
            base_url=overrides.pop("base_url", os.getenv("IAT_API_URL", "http://localhost:8000")),
            api_key=overrides.pop("api_key", os.getenv("IAT_ADMIN_API_KEY")),
            **overrides,
        )

    def discover(self) -> dict[str, Any]:
        return self._request("GET", "/.well-known/iat.json")

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities")

    def services(self) -> dict[str, Any]:
        return self._request("GET", "/services")

    def sandbox_offers(self, *, service: str | None = None) -> dict[str, Any]:
        params = {"service": service} if service else None
        return self._request("GET", "/sandbox/v1/offers", params=params)

    def sandbox_preview(
        self,
        service: str,
        *,
        goal: str,
        max_price: str | int | float,
        strategy: str = "balanced",
        required_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/sandbox/v1/preview",
            json=self._sandbox_payload(
                service,
                goal,
                max_price,
                strategy,
                required_capabilities,
            ),
        )

    def sandbox_buy(
        self,
        service: str,
        *,
        goal: str,
        max_price: str | int | float,
        strategy: str = "balanced",
        required_capabilities: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = idempotency_key or f"iat-sdk-{secrets.token_urlsafe(18)}"
        return self._request(
            "POST",
            "/sandbox/v1/purchase",
            json=self._sandbox_payload(
                service,
                goal,
                max_price,
                strategy,
                required_capabilities,
            ),
            headers={"Idempotency-Key": key},
            retry_safe=True,
        )

    def sandbox_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sandbox/v1/orders/{order_id}")

    def sandbox_feedback(
        self,
        order_id: str,
        *,
        outcome: str,
        feedback_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/sandbox/v1/orders/{order_id}/feedback",
            json={
                "outcome": outcome,
                "feedback_key": feedback_key or f"iat-sdk-{secrets.token_urlsafe(18)}",
            },
        )

    def simulate_decision(
        self,
        candidates: list[Mapping[str, Any]],
        *,
        decision_type: str = "select_offer",
        policy: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/intelligence/v1/decisions/simulate",
            json={
                "decision_type": decision_type,
                "candidates": [dict(item) for item in candidates],
                "policy": dict(policy or {}),
                "context": dict(context or {}),
            },
        )

    def create_order(
        self,
        service: str,
        *,
        query: str | None = None,
        buyer_wallet: str | None = None,
        buyer_intent: Mapping[str, Any] | None = None,
        requirements: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "service": service,
            "query": query,
            "buyer_wallet": buyer_wallet,
            "buyer_intent": dict(buyer_intent or {}),
            "requirements": dict(requirements or {}),
        }
        return self._request("POST", "/create-order", json=payload)

    def verify_payment(self, order_id: str, transaction_signature: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/buyer/verify-payment",
            json={"order_id": order_id, "tx_signature": transaction_signature},
        )

    @staticmethod
    def _sandbox_payload(
        service: str,
        goal: str,
        max_price: str | int | float,
        strategy: str,
        required_capabilities: list[str] | None,
    ) -> dict[str, Any]:
        return {
            "service": service,
            "goal": goal,
            "max_price": str(max_price),
            "strategy": strategy,
            "required_capabilities": list(required_capabilities or []),
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        retry_safe: bool | None = None,
    ) -> dict[str, Any]:
        normalized_method = method.upper()
        safe_to_retry = retry_safe if retry_safe is not None else normalized_method in {"GET", "HEAD"}
        request_headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.api_key:
            request_headers["x-api-key"] = self.api_key
        request_headers.update(headers or {})
        url = urljoin(self.base_url, path.lstrip("/"))
        last_transport_error: Exception | None = None

        for attempt in range(1, self.retry_policy.attempts + 1):
            try:
                response = self.session.request(
                    normalized_method,
                    url,
                    json=json,
                    params=params,
                    headers=request_headers,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_transport_error = exc
                if not safe_to_retry or attempt == self.retry_policy.attempts:
                    break
                self._backoff(attempt)
                continue

            if (
                safe_to_retry
                and response.status_code in self.retry_policy.retry_statuses
                and attempt < self.retry_policy.attempts
            ):
                self._backoff(attempt)
                continue

            payload = self._decode_response(response)
            if not 200 <= response.status_code < 300:
                detail = payload.get("detail") if isinstance(payload, dict) else None
                raise IATAPIError(
                    "api_request_failed",
                    str(detail or f"IAT API returned HTTP {response.status_code}"),
                    status_code=response.status_code,
                    details=payload,
                )
            if not isinstance(payload, dict):
                raise IATAPIError(
                    "invalid_response_shape",
                    "IAT API response must be a JSON object",
                    status_code=response.status_code,
                )
            return payload

        raise IATTransportError(
            "transport_failed",
            "IAT API could not be reached after bounded retries",
            details={"error_type": type(last_transport_error).__name__},
        ) from last_transport_error

    @staticmethod
    def _decode_response(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise IATAPIError(
                "invalid_json_response",
                "IAT API returned a non-JSON response",
                status_code=response.status_code,
            ) from exc

    def _backoff(self, attempt: int) -> None:
        delay = min(
            self.retry_policy.maximum_delay,
            self.retry_policy.initial_delay * (2 ** (attempt - 1)),
        )
        if delay:
            time.sleep(delay)
