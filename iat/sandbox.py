"""Isolated, deterministic buyer sandbox with bounded adaptive scoring."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

from iat.intelligence.decision_core import DecisionPolicy, evaluate_candidates


SANDBOX_VERSION = "iat_buyer_sandbox_v1"
MAX_BUDGET = Decimal("1000000")
MAX_RECORDS = 1_000
MAX_FEEDBACK_PER_ORDER = 64
_MONEY_STEP = Decimal("0.000001")


class SandboxValidationError(ValueError):
    """Raised when a request violates a sandbox contract or policy."""


class SandboxConflictError(ValueError):
    """Raised when an idempotency key is reused with a different request."""


class SandboxNotFoundError(LookupError):
    """Raised when an order does not exist."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(value: Any, *, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SandboxValidationError(f"{field_name}_must_be_decimal") from exc
    if not amount.is_finite() or amount < 0 or amount > MAX_BUDGET:
        raise SandboxValidationError(f"{field_name}_out_of_range")
    return amount.quantize(_MONEY_STEP, rounding=ROUND_HALF_UP)


def _clean_string(value: Any, *, field_name: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise SandboxValidationError(f"{field_name}_required")
    if len(text) > maximum:
        raise SandboxValidationError(f"{field_name}_too_long")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
        raise SandboxValidationError(f"{field_name}_contains_control_characters")
    return text


@dataclass(frozen=True)
class SandboxOffer:
    offer_id: str
    service: str
    supplier_id: str
    price: Decimal
    currency: str
    quality: float
    trust: float
    reliability: float
    latency_ms: int
    capabilities: tuple[str, ...] = ()
    data_policy: str = "no_training"

    def public(self, learned_adjustment: float = 0.0) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "service": self.service,
            "supplier_id": self.supplier_id,
            "price": str(self.price),
            "currency": self.currency,
            "quality_score": self.quality,
            "trust_score": self.trust,
            "reliability_score": self.reliability,
            "latency_ms": self.latency_ms,
            "capabilities": list(self.capabilities),
            "data_policy": self.data_policy,
            "learned_adjustment": round(learned_adjustment, 4),
        }


@dataclass
class _LearningState:
    positive: int = 0
    negative: int = 0

    def adjustment(self) -> float:
        observations = self.positive + self.negative
        if observations == 0:
            return 0.0
        confidence = min(1.0, observations / 20.0)
        sentiment = (self.positive - self.negative) / observations
        return round(max(-5.0, min(5.0, sentiment * confidence * 5.0)), 4)


DEFAULT_OFFERS = (
    SandboxOffer(
        offer_id="sandbox-risk-balanced",
        service="risk_report",
        supplier_id="sandbox_supplier_balanced",
        price=Decimal("0.800000"),
        currency="IAT",
        quality=88.0,
        trust=91.0,
        reliability=94.0,
        latency_ms=1_200,
        capabilities=("risk_analysis", "summarization"),
    ),
    SandboxOffer(
        offer_id="sandbox-risk-premium",
        service="risk_report",
        supplier_id="sandbox_supplier_premium",
        price=Decimal("1.400000"),
        currency="IAT",
        quality=97.0,
        trust=96.0,
        reliability=98.0,
        latency_ms=1_800,
        capabilities=("risk_analysis", "source_verification", "explainability"),
    ),
    SandboxOffer(
        offer_id="sandbox-research-fast",
        service="web_research",
        supplier_id="sandbox_supplier_fast",
        price=Decimal("0.600000"),
        currency="IAT",
        quality=82.0,
        trust=87.0,
        reliability=92.0,
        latency_ms=600,
        capabilities=("web_search", "summarization"),
    ),
    SandboxOffer(
        offer_id="sandbox-research-deep",
        service="web_research",
        supplier_id="sandbox_supplier_deep",
        price=Decimal("1.800000"),
        currency="IAT",
        quality=96.0,
        trust=95.0,
        reliability=96.0,
        latency_ms=2_400,
        capabilities=("web_search", "deep_research", "source_verification"),
    ),
)


class BuyerSandbox:
    """Thread-safe sandbox that cannot invoke production execution or settlement."""

    def __init__(
        self,
        offers: Iterable[SandboxOffer] = DEFAULT_OFFERS,
        *,
        signing_key: bytes | None = None,
        max_records: int = MAX_RECORDS,
    ):
        self._offers = tuple(offers)
        self._signing_key = signing_key or secrets.token_bytes(32)
        self._max_records = max(10, int(max_records))
        self._orders: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._idempotency: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._feedback_keys: set[tuple[str, str]] = set()
        self._feedback_counts: dict[str, int] = {}
        self._learning: dict[str, _LearningState] = {}
        self._lock = threading.RLock()

    def list_offers(self, service: str | None = None) -> list[dict[str, Any]]:
        normalized = str(service or "").strip()
        with self._lock:
            return [
                offer.public(self._adjustment(offer.offer_id))
                for offer in self._offers
                if not normalized or offer.service == normalized
            ]

    def preview(
        self,
        *,
        service: str,
        goal: str,
        max_price: Any,
        strategy: str = "balanced",
        required_capabilities: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        request = self._normalize_request(
            service=service,
            goal=goal,
            max_price=max_price,
            strategy=strategy,
            required_capabilities=required_capabilities,
        )
        ranked = self._rank(request)
        selected = ranked[0] if ranked else None
        return {
            "status": "offer_selected" if selected else "no_eligible_offer",
            "sandbox": True,
            "version": SANDBOX_VERSION,
            "request": request,
            "selected_offer": selected,
            "alternatives": ranked[1:4],
            "policy": self._policy_document(),
        }

    def purchase(
        self,
        *,
        service: str,
        goal: str,
        max_price: Any,
        strategy: str = "balanced",
        required_capabilities: Iterable[str] | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        key = _clean_string(idempotency_key, field_name="idempotency_key", maximum=128)
        request = self._normalize_request(
            service=service,
            goal=goal,
            max_price=max_price,
            strategy=strategy,
            required_capabilities=required_capabilities,
        )
        fingerprint = self._fingerprint(request)

        with self._lock:
            previous = self._idempotency.get(key)
            if previous:
                previous_fingerprint, order_id = previous
                if not hmac.compare_digest(previous_fingerprint, fingerprint):
                    raise SandboxConflictError("idempotency_key_reused_with_different_request")
                return dict(self._orders[order_id])

            ranked = self._rank(request)
            if not ranked:
                raise SandboxValidationError("no_eligible_offer")

            selected = ranked[0]
            order_id = f"sandbox_ord_{secrets.token_hex(12)}"
            result = self._simulate_result(request, selected)
            receipt_payload = {
                "order_id": order_id,
                "offer_id": selected["offer_id"],
                "price": selected["price"],
                "currency": selected["currency"],
                "request_fingerprint": fingerprint,
            }
            receipt = hmac.new(
                self._signing_key,
                self._canonical(receipt_payload),
                hashlib.sha256,
            ).hexdigest()
            order = {
                "status": "completed",
                "sandbox": True,
                "production_side_effects": False,
                "funds_moved": False,
                "order_id": order_id,
                "created_at": _utc_now(),
                "request": request,
                "selected_offer": selected,
                "selection_explanation": selected["selection_explanation"],
                "result": result,
                "receipt": {
                    "algorithm": "hmac-sha256",
                    "scope": "sandbox_only",
                    "payload": receipt_payload,
                    "signature": receipt,
                },
            }
            self._orders[order_id] = order
            self._idempotency[key] = (fingerprint, order_id)
            self._trim()
            return dict(order)

    def get_order(self, order_id: str) -> dict[str, Any]:
        normalized = _clean_string(order_id, field_name="order_id", maximum=128)
        with self._lock:
            order = self._orders.get(normalized)
            if not order:
                raise SandboxNotFoundError("sandbox_order_not_found")
            return dict(order)

    def record_feedback(
        self,
        order_id: str,
        *,
        outcome: str,
        feedback_key: str,
    ) -> dict[str, Any]:
        normalized_outcome = str(outcome or "").strip().lower()
        if normalized_outcome not in {"positive", "negative"}:
            raise SandboxValidationError("outcome_must_be_positive_or_negative")
        normalized_key = _clean_string(feedback_key, field_name="feedback_key", maximum=128)

        with self._lock:
            order = self.get_order(order_id)
            unique_key = (order["order_id"], normalized_key)
            if unique_key in self._feedback_keys:
                return {
                    "status": "already_recorded",
                    "order_id": order["order_id"],
                    "adaptation": self._adaptation_for_order(order),
                }
            feedback_count = self._feedback_counts.get(order["order_id"], 0)
            if feedback_count >= MAX_FEEDBACK_PER_ORDER:
                raise SandboxValidationError("feedback_limit_reached")
            offer_id = order["selected_offer"]["offer_id"]
            state = self._learning.setdefault(offer_id, _LearningState())
            if normalized_outcome == "positive":
                state.positive += 1
            else:
                state.negative += 1
            self._feedback_keys.add(unique_key)
            self._feedback_counts[order["order_id"]] = feedback_count + 1
            return {
                "status": "recorded",
                "order_id": order["order_id"],
                "adaptation": self._adaptation_for_order(order),
            }

    def _normalize_request(
        self,
        *,
        service: str,
        goal: str,
        max_price: Any,
        strategy: str,
        required_capabilities: Iterable[str] | None,
    ) -> dict[str, Any]:
        normalized_strategy = str(strategy or "balanced").strip().lower()
        if normalized_strategy not in {"balanced", "cheapest", "fastest", "safest", "quality"}:
            raise SandboxValidationError("unsupported_strategy")
        capabilities = sorted(
            {
                _clean_string(item, field_name="capability", maximum=64).lower()
                for item in (required_capabilities or [])
            }
        )
        if len(capabilities) > 20:
            raise SandboxValidationError("too_many_required_capabilities")
        return {
            "service": _clean_string(service, field_name="service", maximum=80).lower(),
            "goal": _clean_string(goal, field_name="goal", maximum=4_000),
            "max_price": str(_money(max_price, field_name="max_price")),
            "currency": "IAT",
            "strategy": normalized_strategy,
            "required_capabilities": capabilities,
        }

    def _rank(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        maximum = Decimal(request["max_price"])
        required = set(request["required_capabilities"])
        eligible = [
            offer
            for offer in self._offers
            if offer.service == request["service"]
            and offer.currency == request["currency"]
            and offer.price <= maximum
            and required.issubset(set(offer.capabilities))
        ]
        decision = evaluate_candidates(
            [
                {
                    "candidate_id": offer.offer_id,
                    "price": float(offer.price),
                    "quality": offer.quality,
                    "trust": offer.trust,
                    "reliability": offer.reliability,
                    "latency_score": max(
                        0.0,
                        100.0 - math.log10(max(10, offer.latency_ms)) * 25.0,
                    ),
                    "capabilities": list(offer.capabilities),
                }
                for offer in eligible
            ],
            policy=DecisionPolicy(
                strategy=request["strategy"],
                maximum_price=float(maximum),
                required_capabilities=tuple(required),
            ),
            decision_type="select_sandbox_offer",
            context={"service": request["service"]},
        )
        core_scores = {
            item["candidate_id"]: item
            for item in decision["ranked_candidates"]
        }
        ranked = []
        for offer in eligible:
            core = core_scores[offer.offer_id]
            learned = self._adjustment(offer.offer_id)
            score = round(max(0.0, min(100.0, core["score"] + learned)), 4)
            components = {
                **core["metrics"],
                "bounded_learning": learned,
                "weighted_contributions": core["contributions"],
            }
            public = offer.public(self._adjustment(offer.offer_id))
            public.update(
                {
                    "selection_score": score,
                    "score_components": components,
                    "selection_explanation": self._explain(offer, request["strategy"], score),
                }
            )
            ranked.append(public)
        return sorted(ranked, key=lambda item: (-item["selection_score"], item["offer_id"]))

    def _score(
        self,
        offer: SandboxOffer,
        strategy: str,
        maximum: Decimal,
    ) -> tuple[float, dict[str, float]]:
        price_score = float((Decimal("1") - (offer.price / maximum)) * 100) if maximum else 0.0
        price_score = max(0.0, min(100.0, price_score))
        latency_score = max(0.0, 100.0 - math.log10(max(10, offer.latency_ms)) * 25.0)
        weights = {
            "balanced": (0.25, 0.25, 0.20, 0.20, 0.10),
            "cheapest": (0.65, 0.10, 0.10, 0.10, 0.05),
            "fastest": (0.10, 0.10, 0.10, 0.15, 0.55),
            "safest": (0.10, 0.15, 0.35, 0.35, 0.05),
            "quality": (0.10, 0.55, 0.15, 0.15, 0.05),
        }[strategy]
        learned = self._adjustment(offer.offer_id)
        base = (
            price_score * weights[0]
            + offer.quality * weights[1]
            + offer.trust * weights[2]
            + offer.reliability * weights[3]
            + latency_score * weights[4]
        )
        return round(max(0.0, min(100.0, base + learned)), 4), {
            "price": round(price_score, 4),
            "quality": offer.quality,
            "trust": offer.trust,
            "reliability": offer.reliability,
            "latency": round(latency_score, 4),
            "bounded_learning": learned,
        }

    def _adjustment(self, offer_id: str) -> float:
        return self._learning.get(offer_id, _LearningState()).adjustment()

    @staticmethod
    def _explain(offer: SandboxOffer, strategy: str, score: float) -> dict[str, Any]:
        return {
            "reason": "highest_policy_compliant_score",
            "strategy": strategy,
            "score": score,
            "facts": [
                f"price={offer.price} {offer.currency}",
                f"quality={offer.quality}",
                f"trust={offer.trust}",
                f"reliability={offer.reliability}",
                f"latency_ms={offer.latency_ms}",
            ],
        }

    @staticmethod
    def _simulate_result(request: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "sandbox_simulation",
            "service": request["service"],
            "summary": "The request completed inside the isolated IAT buyer sandbox.",
            "goal_digest": hashlib.sha256(request["goal"].encode("utf-8")).hexdigest(),
            "supplier_id": selected["supplier_id"],
            "evidence": [
                {
                    "type": "policy_evaluation",
                    "verified": True,
                    "details": "budget, capability, and strategy constraints satisfied",
                }
            ],
        }

    def _adaptation_for_order(self, order: dict[str, Any]) -> dict[str, Any]:
        offer_id = order["selected_offer"]["offer_id"]
        state = self._learning.get(offer_id, _LearningState())
        return {
            "scope": "sandbox_only",
            "offer_id": offer_id,
            "positive_observations": state.positive,
            "negative_observations": state.negative,
            "score_adjustment": state.adjustment(),
            "minimum": -5.0,
            "maximum": 5.0,
            "policy_mutation_allowed": False,
            "production_effect": False,
        }

    @staticmethod
    def _policy_document() -> dict[str, Any]:
        return {
            "budget_enforced": True,
            "required_capabilities_enforced": True,
            "external_calls_allowed": False,
            "funds_allowed": False,
            "learning_scope": "sandbox_only",
            "learning_adjustment_bounds": [-5.0, 5.0],
        }

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _fingerprint(self, request: dict[str, Any]) -> str:
        return hashlib.sha256(self._canonical(request)).hexdigest()

    def _trim(self) -> None:
        while len(self._orders) > self._max_records:
            order_id, _ = self._orders.popitem(last=False)
            stale_keys = [
                key for key, (_, associated_order_id) in self._idempotency.items()
                if associated_order_id == order_id
            ]
            for key in stale_keys:
                self._idempotency.pop(key, None)
            self._feedback_counts.pop(order_id, None)
            self._feedback_keys = {
                feedback for feedback in self._feedback_keys if feedback[0] != order_id
            }
