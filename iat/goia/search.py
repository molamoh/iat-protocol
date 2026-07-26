"""Deterministic local GOIA search with commission-neutral ranking."""

from __future__ import annotations

import json
import re
import time
from decimal import Decimal
from typing import Any

from iat.goia.contracts import SearchIntent
from iat.goia.repository import list_current_observations


_TOKEN = re.compile(r"[a-zA-ZÀ-ÿ0-9]{2,}")


def _tokens(value: str) -> set[str]:
    return {item.lower() for item in _TOKEN.findall(value)}


def _countries(manifest_json: str) -> set[str]:
    try:
        return set(json.loads(manifest_json).get("countries") or [])
    except (TypeError, ValueError):
        return set()


def search_local_index(
    intent: SearchIntent,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    timestamp = int(now or time.time())
    if intent.required or intent.preferred:
        return {
            "status": "unsupported_constraints",
            "index": "local",
            "search_performed": False,
            "network_access": False,
            "result_count": 0,
            "results": [],
            "unsupported_attributes": sorted(
                {
                    requirement.attribute
                    for requirement in [*intent.required, *intent.preferred]
                }
            ),
            "as_of": timestamp,
        }
    maximum = (
        Decimal(intent.maximum_total_price)
        if intent.maximum_total_price is not None
        else None
    )
    query_tokens = _tokens(intent.query)
    rows = list_current_observations(
        kind=intent.kind,
        currency=intent.currency,
        now=timestamp,
    )
    eligible: list[dict[str, Any]] = []
    seen_offers: set[tuple[str, str]] = set()

    for row in rows:
        identity = (row["merchant_id"], row["offer_id"])
        if identity in seen_offers:
            continue
        seen_offers.add(identity)
        if intent.country not in _countries(row["manifest_json"]):
            continue
        price = Decimal(row["total_price"])
        if maximum is not None and price > maximum:
            continue
        title_tokens = _tokens(row["title"])
        overlap = len(query_tokens & title_tokens)
        if query_tokens and overlap == 0:
            continue
        text_score = 40 if not query_tokens else round(40 * overlap / len(query_tokens), 6)
        price_score = (
            Decimal("20")
            if maximum is None
            else max(Decimal("0"), (Decimal("1") - price / maximum) * Decimal("20"))
        )
        confidence_score = Decimal(row["attribute_confidence"]) * Decimal("0.25")
        lifetime = max(1, int(row["expires_at"]) - int(row["observed_at"]))
        remaining = max(0, int(row["expires_at"]) - timestamp)
        freshness_score = Decimal(str(min(1, remaining / lifetime))) * Decimal("15")
        organic_score = (
            Decimal(str(text_score)) + price_score + confidence_score + freshness_score
        ).quantize(Decimal("0.000001"))
        payload = json.loads(row["payload_json"])
        eligible.append(
            {
                "observation": payload,
                "organic_score": str(organic_score),
                "organic_factors": {
                    "query_match": str(Decimal(str(text_score))),
                    "price": str(price_score.quantize(Decimal("0.000001"))),
                    "confidence": str(confidence_score.quantize(Decimal("0.000001"))),
                    "freshness": str(freshness_score.quantize(Decimal("0.000001"))),
                },
                "commercial_disclosure": {
                    "commercial_relationship": row["commercial_relationship"],
                    "sponsored": bool(row["sponsored"]),
                    "commission_may_be_earned": row["commercial_relationship"]
                    in {"affiliate", "direct_partner"},
                    "commission_changes_organic_rank": False,
                },
            }
        )

    eligible.sort(
        key=lambda item: (
            -Decimal(item["organic_score"]),
            Decimal(item["observation"]["total_price"]),
            item["observation"]["observation_id"],
        )
    )
    results = eligible[: intent.result_limit]
    for index, result in enumerate(results, start=1):
        result["organic_rank"] = index
    return {
        "status": "ok",
        "index": "local",
        "search_performed": True,
        "network_access": False,
        "result_count": len(results),
        "results": results,
        "policy": {
            "version": "goia_organic_ranking_v1",
            "commission_changes_organic_rank": False,
            "sponsored_results_separate_from_organic": True,
        },
        "as_of": timestamp,
    }
