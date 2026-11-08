"""Insulin log. Parents record doses; the child's "I had it with lunch" answers are
recorded as reports without units. SugarScout only records and shows insulin; it never
calculates, suggests or checks a dose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from sugarscout.api.deps import DemoKey, EngineDep, RedisDep, enqueue
from sugarscout.demo import DEMO_CHILD_ID
from sugarscout.sim.cgm import add_effect

router = APIRouter(prefix="/insulin", tags=["insulin"])

Kind = Literal["meal", "correction", "long_acting", "unknown"]


class DoseIn(BaseModel):
    kind: Kind = "meal"
    units: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2)
    given_at: datetime | None = None
    note: str | None = Field(default=None, max_length=200)


class DoseOut(BaseModel):
    id: int
    given_at: datetime
    units: Decimal | None
    kind: str
    source: str
    note: str | None


@router.post("", response_model=DoseOut, dependencies=[DemoKey])
async def log_dose(body: DoseIn, request: Request, engine: EngineDep, redis: RedisDep) -> DoseOut:
    now = datetime.now(UTC)
    given_at = body.given_at or now
    if given_at > now + timedelta(minutes=5):
        raise HTTPException(422, "Insulin can't be logged in the future")
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """INSERT INTO insulin_doses (child_id, given_at, units, kind, source, note)
                       VALUES (:c, :at, :u, :k, 'parent', :n)
                       RETURNING id, given_at, units, kind, source, note"""
                ),
                {
                    "c": DEMO_CHILD_ID,
                    "at": given_at,
                    "u": body.units,
                    "k": body.kind,
                    "n": body.note,
                },
            )
        ).one()
    # Demo simulator: insulin flattens a meal rise (no dosing maths; see sim/cgm.py).
    if body.kind != "long_acting":
        await add_effect(redis, "insulin")
    await enqueue(request, "agent_tick")
    return DoseOut.model_validate(row._mapping)


@router.get("", response_model=list[DoseOut])
async def list_doses(engine: EngineDep, days: int = Query(1, ge=1, le=30)) -> list[DoseOut]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT id, given_at, units, kind, source, note FROM insulin_doses
                       WHERE child_id = :c AND given_at >= now() - make_interval(days => :d)
                       ORDER BY given_at DESC"""
                ),
                {"c": DEMO_CHILD_ID, "d": days},
            )
        ).all()
    return [DoseOut.model_validate(r._mapping) for r in rows]
