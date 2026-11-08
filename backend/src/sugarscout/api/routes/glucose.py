"""Glucose reads for the parent dashboard.

Live view reads raw readings; the week view reads the hourly continuous aggregate
(Section 18.6). The demo has one child, so routes don't take a child id yet.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

from sugarscout.api.deps import EngineDep, SettingsDep
from sugarscout.demo import DEMO_CHILD_ID

router = APIRouter(prefix="/glucose", tags=["glucose"])


class Point(BaseModel):
    ts: datetime
    value: int
    trend: str | None


class Latest(BaseModel):
    ts: datetime | None
    value: int | None
    trend: str | None
    age_s: float | None
    stale: bool


class HourPoint(BaseModel):
    bucket: datetime
    avg: float
    min: int
    max: int
    n: int


@router.get("/latest", response_model=Latest)
async def latest(engine: EngineDep, settings: SettingsDep) -> Latest:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """SELECT ts, value_mg_dl, trend FROM glucose_readings
                       WHERE child_id = :c ORDER BY ts DESC LIMIT 1"""
                ),
                {"c": DEMO_CHILD_ID},
            )
        ).first()
    if row is None:
        return Latest(ts=None, value=None, trend=None, age_s=None, stale=True)
    age = (datetime.now(UTC) - row.ts).total_seconds()
    return Latest(
        ts=row.ts,
        value=row.value_mg_dl,
        trend=row.trend,
        age_s=round(age, 1),
        stale=age >= settings.rule_data_gap_seconds,
    )


@router.get("/live", response_model=list[Point])
async def live(engine: EngineDep, minutes: int = Query(10, ge=1, le=120)) -> list[Point]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT ts, value_mg_dl, trend FROM glucose_readings
                       WHERE child_id = :c AND ts > now() - make_interval(mins => :m)
                       ORDER BY ts"""
                ),
                {"c": DEMO_CHILD_ID, "m": minutes},
            )
        ).all()
    return [Point(ts=r.ts, value=r.value_mg_dl, trend=r.trend) for r in rows]


@router.get("/week", response_model=list[HourPoint])
async def week(engine: EngineDep, days: int = Query(7, ge=1, le=30)) -> list[HourPoint]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT bucket, avg_mg_dl, min_mg_dl, max_mg_dl, n FROM glucose_hourly
                       WHERE child_id = :c AND bucket >= now() - make_interval(days => :d)
                       ORDER BY bucket"""
                ),
                {"c": DEMO_CHILD_ID, "d": days},
            )
        ).all()
    return [
        HourPoint(
            bucket=r.bucket,
            avg=round(float(r.avg_mg_dl), 1),
            min=r.min_mg_dl,
            max=r.max_mg_dl,
            n=r.n,
        )
        for r in rows
    ]


class ForecastOut(BaseModel):
    made_at: datetime | None
    predicted: int | None
    horizon_min: int | None
    slope_per_5min: float | None
    mae_24h: float | None  # mean absolute error of scored forecasts, mg/dL
    scored_24h: int


@router.get("/forecast", response_model=ForecastOut)
async def latest_forecast(engine: EngineDep, settings: SettingsDep) -> ForecastOut:
    """The latest ~20-minute forecast and how accurate recent forecasts have been."""
    async with engine.connect() as conn:
        latest_row = (
            await conn.execute(
                text(
                    """SELECT made_at, predicted, horizon_min, slope_per_5min FROM forecasts
                       WHERE child_id = :c AND made_at > now() - make_interval(secs => :fresh)
                       ORDER BY made_at DESC LIMIT 1"""
                ),
                {"c": DEMO_CHILD_ID, "fresh": settings.sim_tick_seconds * 3},
            )
        ).first()
        acc = (
            await conn.execute(
                text(
                    """SELECT round(avg(abs(error))::numeric, 1) AS mae, count(*) AS n
                       FROM forecasts
                       WHERE child_id = :c AND error IS NOT NULL
                         AND made_at > now() - INTERVAL '24 hours'"""
                ),
                {"c": DEMO_CHILD_ID},
            )
        ).one()
    return ForecastOut(
        made_at=latest_row.made_at if latest_row else None,
        predicted=latest_row.predicted if latest_row else None,
        horizon_min=latest_row.horizon_min if latest_row else None,
        slope_per_5min=float(latest_row.slope_per_5min) if latest_row else None,
        mae_24h=float(acc.mae) if acc.mae is not None else None,
        scored_24h=int(acc.n),
    )
