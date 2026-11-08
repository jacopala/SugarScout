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
