"""Short-horizon glucose forecast: linear trend extrapolation.

The same idea commercial CGMs use for "urgent low soon" alerts: fit a line through the
last few readings and project it ~20 minutes ahead. Deterministic, transparent and
testable; every forecast is stored and later scored against what actually happened.

Readings are treated as one CGM interval (5 min) apart, so the forecast is independent
of the demo simulator's sped-up clock.
"""

from __future__ import annotations

from dataclasses import dataclass

CGM_INTERVAL_MIN = 5
MIN_VALUE, MAX_VALUE = 40, 400


@dataclass(frozen=True)
class Forecast:
    predicted: int  # mg/dL at the horizon
    slope_per_5min: float  # mg/dL per reading
    horizon_min: int
    r2: float  # how well a straight line fits the recent readings (0..1)
    latest: int


def forecast(values: list[int], window: int = 4, horizon_readings: int = 4) -> Forecast | None:
    """Least-squares line over the last `window` values, projected `horizon_readings` ahead."""
    if len(values) < window:
        return None
    ys = [float(v) for v in values[-window:]]
    n = len(ys)
    xs = [float(i) for i in range(n)]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    syy = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    r2 = 1.0 - ss_res / syy if syy else 1.0
    predicted = intercept + slope * (n - 1 + horizon_readings)
    return Forecast(
        predicted=round(max(MIN_VALUE, min(MAX_VALUE, predicted))),
        slope_per_5min=round(slope, 2),
        horizon_min=horizon_readings * CGM_INTERVAL_MIN,
        r2=round(max(0.0, r2), 3),
        latest=int(values[-1]),
    )
