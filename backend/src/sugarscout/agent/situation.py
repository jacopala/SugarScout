"""The agent's view of right now: every data source, reduced to plain facts.

Everything here is deterministic. Times are in "CGM minutes" (one simulator reading
stands for one 5-minute CGM reading), so the same logic works for a real sensor.
The concern level is computed in code: the AI may only send a parent heads-up when
concern is 1 or higher.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.mood import MOOD_LABELS
from sugarscout.rules.forecast import forecast
from sugarscout.settings import Settings


def cgm_minutes(real_seconds: float, tick_s: int) -> float:
    return real_seconds / max(1, tick_s) * 5


def real_seconds(cgm_min: float, tick_s: int) -> float:
    return cgm_min / 5 * max(1, tick_s)


@dataclass
class Situation:
    child_name: str
    glucose: int | None = None
    glucose_stale: bool = True
    slope_per_5min: float | None = None
    forecast: int | None = None
    forecast_horizon_min: int | None = None
    forecast_mae: float | None = None  # how far off recent forecasts were, mg/dL
    last_meal_id: int | None = None
    last_meal: str | None = None
    last_meal_carbs_g: float | None = None
    minutes_since_meal: float | None = None
    meal_covered_by_insulin: bool | None = None
    minutes_since_insulin: float | None = None
    last_insulin_source: str | None = None
    latest_mood: int | None = None
    minutes_since_mood: float | None = None
    after_meal_mood_logged: bool = False
    checkin_today: bool = False
    open_alerts: list[str] = field(default_factory=list)
    pending_question: str | None = None
    minutes_since_asked: dict[str, float] = field(default_factory=dict)
    answered_for_meal: list[str] = field(default_factory=list)  # questions answered about last meal
    concern: int = 0
    concern_reasons: list[str] = field(default_factory=list)

    def facts(self) -> dict[str, Any]:
        """Compact facts for the model prompt and the audit trail."""
        d = asdict(self)
        d.pop("minutes_since_asked")
        return {
            k: (round(v, 1) if isinstance(v, float) else v)
            for k, v in d.items()
            if v not in (None, [], {})
        }


def assess_concern(s: Situation, high: int = 250) -> None:
    """Deterministic concern level (0 none, 1 watch, 2 tell the parent soon) with reasons."""
    level, reasons = 0, []

    def raise_to(n: int, why: str) -> None:
        nonlocal level
        level = max(level, n)
        reasons.append(why)

    if s.glucose is not None and not s.glucose_stale:
        if s.forecast is not None and s.slope_per_5min is not None and s.slope_per_5min < -1:
            if s.forecast < 70:
                raise_to(2, f"heading low: about {s.forecast} in ~{s.forecast_horizon_min} min")
            elif s.forecast < 85:
                raise_to(1, f"drifting down toward {s.forecast}")
        meal_recent = s.minutes_since_meal is not None and s.minutes_since_meal <= 120
        rising = s.slope_per_5min is not None and s.slope_per_5min >= 2
        if meal_recent and rising and s.meal_covered_by_insulin is False:
            carbs = f"~{round(s.last_meal_carbs_g)} g carbs" if s.last_meal_carbs_g else "a meal"
            if s.glucose >= 180:
                raise_to(2, f"rising to {s.glucose} after {carbs} with no insulin logged")
            else:
                raise_to(1, f"rising after {carbs} with no insulin logged")
        if s.glucose > high:
            raise_to(2, f"high: {s.glucose}")
    if s.latest_mood is not None and s.latest_mood <= 2 and (s.minutes_since_mood or 0) <= 90:
        raise_to(1, f"said they feel {MOOD_LABELS[s.latest_mood]}")

    s.concern, s.concern_reasons = level, reasons


async def build_situation(
    engine: AsyncEngine, settings: Settings, child_id: uuid.UUID, now: datetime
) -> Situation:
    tick = settings.sim_tick_seconds
    s = Situation(child_name=settings.demo_child_name)
    async with engine.connect() as conn:
        readings = (
            await conn.execute(
                text(
                    """SELECT ts, value_mg_dl FROM glucose_readings
                       WHERE child_id = :c AND ts > :since ORDER BY ts"""
                ),
                {"c": child_id, "since": now - timedelta(seconds=tick * 8)},
            )
        ).all()
        if readings:
            s.glucose = int(readings[-1].value_mg_dl)
            s.glucose_stale = (
                now - readings[-1].ts
            ).total_seconds() > settings.rule_data_gap_seconds
            fc = forecast([int(r.value_mg_dl) for r in readings])
            if fc is not None:
                s.slope_per_5min, s.forecast, s.forecast_horizon_min = (
                    fc.slope_per_5min,
                    fc.predicted,
                    fc.horizon_min,
                )
        mae = (
            await conn.execute(
                text(
                    """SELECT avg(abs(error)) FROM forecasts
                       WHERE child_id = :c AND error IS NOT NULL AND made_at > :since"""
                ),
                {"c": child_id, "since": now - timedelta(hours=24)},
            )
        ).scalar_one()
        s.forecast_mae = float(mae) if mae is not None else None

        meal = (
            await conn.execute(
                text(
                    """SELECT id, description, created_at,
                              (analysis->>'total_carbs_g')::float AS carbs
                       FROM meals WHERE child_id = :c ORDER BY created_at DESC LIMIT 1"""
                ),
                {"c": child_id},
            )
        ).first()
        insulin = (
            await conn.execute(
                text(
                    """SELECT given_at, source FROM insulin_doses
                       WHERE child_id = :c AND kind <> 'long_acting'
                       ORDER BY given_at DESC LIMIT 1"""
                ),
                {"c": child_id},
            )
        ).first()
        if insulin is not None:
            s.minutes_since_insulin = cgm_minutes((now - insulin.given_at).total_seconds(), tick)
            s.last_insulin_source = insulin.source
        if meal is not None:
            s.last_meal_id = int(meal.id)
            s.last_meal = meal.description
            s.last_meal_carbs_g = meal.carbs
            s.minutes_since_meal = cgm_minutes((now - meal.created_at).total_seconds(), tick)
            window = real_seconds(30, tick)
            s.meal_covered_by_insulin = bool(
                (
                    insulin is not None
                    and abs((insulin.given_at - meal.created_at).total_seconds()) <= window
                )
                or (insulin is not None and insulin.given_at > meal.created_at)
            )
            answered = (
                (
                    await conn.execute(
                        text(
                            """SELECT DISTINCT question FROM agent_questions
                           WHERE child_id = :c AND meal_id = :m AND answered_at IS NOT NULL"""
                        ),
                        {"c": child_id, "m": meal.id},
                    )
                )
                .scalars()
                .all()
            )
            s.answered_for_meal = list(answered)
            s.after_meal_mood_logged = bool(
                (
                    await conn.execute(
                        text(
                            """SELECT EXISTS (SELECT 1 FROM mood_checkins
                               WHERE child_id = :c AND meal_id = :m)"""
                        ),
                        {"c": child_id, "m": meal.id},
                    )
                ).scalar_one()
            )

        mood_row = (
            await conn.execute(
                text(
                    """SELECT mood, created_at FROM mood_checkins
                       WHERE child_id = :c ORDER BY created_at DESC LIMIT 1"""
                ),
                {"c": child_id},
            )
        ).first()
        if mood_row is not None:
            s.latest_mood = int(mood_row.mood)
            s.minutes_since_mood = cgm_minutes((now - mood_row.created_at).total_seconds(), tick)
            s.checkin_today = mood_row.created_at.date() == now.date()

        s.open_alerts = list(
            (
                await conn.execute(
                    text(
                        "SELECT rule_type FROM alerts WHERE child_id = :c AND state <> 'resolved'"
                    ),
                    {"c": child_id},
                )
            )
            .scalars()
            .all()
        )
        pending = (
            await conn.execute(
                text(
                    """SELECT question FROM agent_questions
                       WHERE child_id = :c AND answered_at IS NULL AND expires_at > :now
                       ORDER BY asked_at DESC LIMIT 1"""
                ),
                {"c": child_id, "now": now},
            )
        ).scalar_one_or_none()
        s.pending_question = pending
        asked = (
            await conn.execute(
                text(
                    """SELECT question, max(asked_at) AS at FROM agent_questions
                       WHERE child_id = :c GROUP BY question"""
                ),
                {"c": child_id},
            )
        ).all()
        s.minutes_since_asked = {
            r.question: cgm_minutes((now - r.at).total_seconds(), tick) for r in asked
        }
    assess_concern(s, settings.rule_high)
    return s
