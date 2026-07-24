from datetime import date, timedelta

import pytest

from iat.intelligence.demand_forecasting import DemandForecastError, forecast_demand


def _series(days=35, base=20):
    start = date(2026, 1, 1)
    return [
        {"period": (start + timedelta(days=index)).isoformat(), "demand": base + index}
        for index in range(days)
    ]


def test_forecast_exposes_uncertainty_capacity_and_governance():
    result = forecast_demand(_series(), horizon_days=7, capacity_per_day=40)

    assert len(result["forecast"]) == 7
    assert result["summary"]["trend_direction"] == "growing"
    assert result["summary"]["seasonality_enabled"] is True
    assert result["capacity"]["capacity_shortfall_risk"] is True
    assert result["governance"]["buyer_identifiers_accepted"] is False
    assert result["governance"]["automatic_capacity_change_allowed"] is False


def test_small_or_low_volume_samples_fail_closed():
    with pytest.raises(DemandForecastError, match="observation_count"):
        forecast_demand(_series(days=13))

    low_volume = [
        {**item, "demand": 1}
        for item in _series(days=14)
    ]
    with pytest.raises(DemandForecastError, match="insufficient_aggregated_volume"):
        forecast_demand(low_volume)


def test_missing_and_duplicate_periods_are_rejected():
    missing = _series(days=14)
    missing[5]["period"] = "2026-02-20"
    with pytest.raises(DemandForecastError, match="contiguous"):
        forecast_demand(missing)

    duplicate = _series(days=14)
    duplicate[5]["period"] = duplicate[4]["period"]
    with pytest.raises(DemandForecastError, match="duplicate_period"):
        forecast_demand(duplicate)
