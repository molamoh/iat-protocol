"""Privacy-preserving, deterministic demand forecasting for sellers."""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Any, Iterable, Mapping


MIN_OBSERVATIONS = 14
MIN_TOTAL_EVENTS = 50
MAX_OBSERVATIONS = 365


class DemandForecastError(ValueError):
    pass


def _linear_fit(values: list[float]) -> tuple[float, float]:
    count = len(values)
    mean_x = (count - 1) / 2
    mean_y = statistics.fmean(values)
    denominator = sum((index - mean_x) ** 2 for index in range(count))
    slope = (
        sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values))
        / denominator
        if denominator
        else 0.0
    )
    return mean_y - slope * mean_x, slope


def forecast_demand(
    observations: Iterable[Mapping[str, Any]],
    *,
    horizon_days: int = 7,
    capacity_per_day: int | None = None,
    headroom_ratio: float = .20,
) -> dict[str, Any]:
    rows = []
    for raw in list(observations):
        try:
            period = date.fromisoformat(str(raw.get("period") or ""))
        except ValueError as exc:
            raise DemandForecastError("period_must_be_iso_date") from exc
        demand = raw.get("demand")
        if isinstance(demand, bool):
            raise DemandForecastError("demand_must_be_integer")
        try:
            demand = int(demand)
        except (TypeError, ValueError) as exc:
            raise DemandForecastError("demand_must_be_integer") from exc
        if demand != raw.get("demand") or not 0 <= demand <= 100_000_000:
            raise DemandForecastError("demand_out_of_range")
        rows.append((period, demand))
    if not MIN_OBSERVATIONS <= len(rows) <= MAX_OBSERVATIONS:
        raise DemandForecastError("observation_count_out_of_range")
    rows.sort(key=lambda item: item[0])
    if len({item[0] for item in rows}) != len(rows):
        raise DemandForecastError("duplicate_period")
    if any(
        rows[index][0] - rows[index - 1][0] != timedelta(days=1)
        for index in range(1, len(rows))
    ):
        raise DemandForecastError("daily_series_must_be_contiguous")
    total_events = sum(item[1] for item in rows)
    if total_events < MIN_TOTAL_EVENTS:
        raise DemandForecastError("insufficient_aggregated_volume")
    if not 1 <= int(horizon_days) <= 30:
        raise DemandForecastError("horizon_out_of_range")
    if capacity_per_day is not None and not 0 <= int(capacity_per_day) <= 100_000_000:
        raise DemandForecastError("capacity_out_of_range")
    try:
        headroom = float(headroom_ratio)
    except (TypeError, ValueError) as exc:
        raise DemandForecastError("invalid_headroom_ratio") from exc
    if not math.isfinite(headroom) or not 0 <= headroom <= 2:
        raise DemandForecastError("headroom_ratio_out_of_range")

    values = [float(item[1]) for item in rows]
    training = values[-min(56, len(values)):]
    intercept, slope = _linear_fit(training)
    fitted = [intercept + slope * index for index in range(len(training))]
    residuals = [actual - expected for actual, expected in zip(training, fitted)]
    residual_std = statistics.stdev(residuals) if len(residuals) > 1 else 0.0
    overall_mean = statistics.fmean(training)
    seasonal = {weekday: 1.0 for weekday in range(7)}
    seasonality_enabled = len(rows) >= 28 and overall_mean > 0
    if seasonality_enabled:
        for weekday in range(7):
            samples = [
                float(demand)
                for period, demand in rows[-56:]
                if period.weekday() == weekday
            ]
            seasonal[weekday] = statistics.fmean(samples) / overall_mean if samples else 1.0

    forecasts = []
    start_index = len(training)
    for step in range(1, int(horizon_days) + 1):
        period = rows[-1][0] + timedelta(days=step)
        base = max(0.0, intercept + slope * (start_index + step - 1))
        expected = base * seasonal[period.weekday()]
        uncertainty = 1.96 * residual_std * math.sqrt(1 + step / len(training))
        forecasts.append({
            "period": period.isoformat(),
            "expected_demand": round(expected, 3),
            "lower_95": round(max(0.0, expected - uncertainty), 3),
            "upper_95": round(max(0.0, expected + uncertainty), 3),
        })

    anomalies = []
    if residual_std > 0:
        offset = len(rows) - len(training)
        for index, residual in enumerate(residuals):
            z_score = residual / residual_std
            if abs(z_score) >= 3:
                anomalies.append({
                    "period": rows[offset + index][0].isoformat(),
                    "direction": "spike" if z_score > 0 else "drop",
                    "z_score": round(z_score, 3),
                })
    peak_upper = max(item["upper_95"] for item in forecasts)
    recommended_capacity = math.ceil(peak_upper * (1 + headroom))
    capacity_risk = (
        capacity_per_day is not None
        and capacity_per_day < recommended_capacity
    )
    normalized_error = residual_std / max(1.0, overall_mean)
    confidence = round(
        max(.2, min(.95, .45 + min(len(rows), 56) / 112 - min(.4, normalized_error / 2))),
        3,
    )

    return {
        "status": "ok",
        "forecast_type": "aggregated_daily_demand",
        "forecast": forecasts,
        "summary": {
            "sample_days": len(rows),
            "aggregated_events": total_events,
            "daily_average": round(statistics.fmean(values), 3),
            "daily_trend": round(slope, 6),
            "trend_direction": "growing" if slope > .05 else ("declining" if slope < -.05 else "stable"),
            "confidence": confidence,
            "seasonality_enabled": seasonality_enabled,
        },
        "anomalies": anomalies,
        "capacity": {
            "current_capacity_per_day": capacity_per_day,
            "recommended_capacity_per_day": recommended_capacity,
            "capacity_shortfall_risk": capacity_risk,
            "headroom_ratio": headroom,
        },
        "method": {
            "trend": "bounded_linear_regression_last_56_days",
            "seasonality": "weekday_factor" if seasonality_enabled else "disabled_until_28_days",
            "interval": "95_percent_residual_interval",
            "minimum_observations": MIN_OBSERVATIONS,
            "minimum_aggregated_events": MIN_TOTAL_EVENTS,
        },
        "governance": {
            "aggregated_data_only": True,
            "buyer_identifiers_accepted": False,
            "simulation_only": True,
            "production_side_effects": False,
            "automatic_capacity_change_allowed": False,
            "automatic_price_change_allowed": False,
            "seller_approval_required": True,
        },
    }
