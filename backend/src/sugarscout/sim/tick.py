"""One simulator tick: write a fake reading, evaluate rules on raw data, sync alerts."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.alerts.service import AlertEvent, sync_alerts
from sugarscout.rules.engine import Reading, RulesConfig, Symptom, evaluate
from sugarscout.rules.forecast import Forecast, forecast
from sugarscout.settings import Settings
from sugarscout.sim.cgm import load_state, save_state, step, trend_label


async def recent_readings(
    engine: AsyncEngine, child_id: uuid.UUID, now: datetime, lookback: timedelta
) -> list[Reading]:
    """Raw readings in the lookback window, oldest first (Section 18.5: never aggregates)."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT ts, value_mg_dl FROM glucose_readings
                       WHERE child_id = :c AND ts > :since AND ts <= :now
                       ORDER BY ts"""
                ),
                {"c": child_id, "since": now - lookback, "now": now},
            )
        ).all()
    return [Reading(r.ts, r.value_mg_dl) for r in rows]


async def evaluate_and_sync(
    engine: AsyncEngine,
    redis: Redis,
    settings: Settings,
    child_id: uuid.UUID,
    child_name: str,
    now: datetime,
) -> tuple[list[AlertEvent], list[int]]:
    cfg = RulesConfig.from_settings(settings)
    # Enough history for the longest rule window, and a bit beyond the gap threshold.
    lookback = timedelta(
        seconds=max(
            cfg.data_gap_seconds * 2,
            settings.sim_tick_seconds * (max(cfg.high_consecutive, cfg.rapid_drop_window) + 2),
        )
    )
    readings = await recent_readings(engine, child_id, now, lookback)
    symptom = await recent_symptom(engine, child_id, now, settings)
    evaluation = evaluate(readings, now, cfg, child_name, symptom)
    async with engine.begin() as conn:
        return await sync_alerts(conn, redis, settings, child_id, child_name, evaluation)


SYMPTOM_LABELS = {"shaky": "shaky", "dizzy": "dizzy", "tummy": "a tummy ache"}


async def recent_symptom(
    engine: AsyncEngine, child_id: uuid.UUID, now: datetime, settings: Settings
) -> Symptom | None:
    """The child's latest "How do you feel right now?" answer, if it was a symptom
    and recent (about 30 CGM-minutes)."""
    window = timedelta(seconds=settings.sim_tick_seconds * 6)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """SELECT answer, answered_at FROM agent_questions
                       WHERE child_id = :c AND question = 'symptoms_now' AND answered_at > :since
                       ORDER BY answered_at DESC LIMIT 1"""
                ),
                {"c": child_id, "since": now - window},
            )
        ).first()
    if row is None or row.answer not in SYMPTOM_LABELS:
        return None
    return Symptom(SYMPTOM_LABELS[row.answer], row.answered_at)


async def record_forecast(
    engine: AsyncEngine, settings: Settings, child_id: uuid.UUID, now: datetime
) -> Forecast | None:
    """Store a forecast from the latest readings, and score any earlier forecast whose
    target time has arrived against the reading nearest to it."""
    tick = settings.sim_tick_seconds
    readings = await recent_readings(engine, child_id, now, timedelta(seconds=tick * 6))
    fc = forecast([r.value for r in readings])
    async with engine.begin() as conn:
        if fc is not None:
            await conn.execute(
                text(
                    """INSERT INTO forecasts
                         (child_id, made_at, target_at, horizon_min, predicted, slope_per_5min)
                       VALUES (:c, :now, :target, :h, :p, :s)"""
                ),
                {
                    "c": child_id,
                    "now": now,
                    "target": now + timedelta(seconds=tick * fc.horizon_min / 5),
                    "h": fc.horizon_min,
                    "p": fc.predicted,
                    "s": fc.slope_per_5min,
                },
            )
        await conn.execute(
            text(
                """UPDATE forecasts f SET actual = sub.v, error = sub.v - f.predicted
                   FROM (
                     SELECT f2.id,
                            (SELECT g.value_mg_dl FROM glucose_readings g
                              WHERE g.child_id = f2.child_id
                                AND g.ts BETWEEN f2.target_at - CAST(:half AS interval)
                                    AND f2.target_at + CAST(:half AS interval)
                              ORDER BY abs(extract(epoch FROM g.ts - f2.target_at)) LIMIT 1) AS v
                     FROM forecasts f2
                     WHERE f2.child_id = :c AND f2.actual IS NULL AND f2.target_at <= :now
                   ) sub
                   WHERE f.id = sub.id AND sub.v IS NOT NULL"""
            ),
            {"c": child_id, "now": now, "half": timedelta(seconds=tick)},
        )
    return fc


async def run_tick(
    engine: AsyncEngine,
    redis: Redis,
    settings: Settings,
    child_id: uuid.UUID,
    child_name: str,
    rng: random.Random,
    now: datetime | None = None,
) -> tuple[int | None, list[AlertEvent], list[int]]:
    now = now or datetime.now(UTC)
    state = await load_state(redis)
    value = step(state, rng)
    if value is not None:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """INSERT INTO glucose_readings (child_id, ts, value_mg_dl, trend, source)
                       VALUES (:c, :ts, :v, :t, 'sim')
                       ON CONFLICT (child_id, ts) DO NOTHING"""
                ),
                {"c": child_id, "ts": now, "v": value, "t": trend_label(state.recent)},
            )
    await save_state(redis, state)
    if value is not None:
        await record_forecast(engine, settings, child_id, now)
    events, sms_ids = await evaluate_and_sync(engine, redis, settings, child_id, child_name, now)
    return value, events, sms_ids
