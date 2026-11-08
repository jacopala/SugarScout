"""One simulator tick: write a fake reading, evaluate rules on raw data, sync alerts."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.alerts.service import AlertEvent, sync_alerts
from sugarscout.rules.engine import Reading, RulesConfig, evaluate
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
    evaluation = evaluate(readings, now, cfg, child_name)
    async with engine.begin() as conn:
        return await sync_alerts(conn, redis, settings, child_id, child_name, evaluation)


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
    events, sms_ids = await evaluate_and_sync(engine, redis, settings, child_id, child_name, now)
    return value, events, sms_ids
