"""Forecast math, predictive rules, symptom rule, and forecast scoring."""

from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.rules.engine import Reading, RulesConfig, Symptom, evaluate
from sugarscout.rules.forecast import forecast
from sugarscout.settings import Settings
from sugarscout.sim.cgm import Scenario, SimState, save_state, set_scenario
from sugarscout.sim.tick import run_tick

CFG = RulesConfig()
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def trace(*values: int) -> list[Reading]:
    return [Reading(T0 + timedelta(seconds=5 * i), v) for i, v in enumerate(values)]


def hit_types(values: list[int], symptom: Symptom | None = None) -> set[str]:
    r = trace(*values)
    return set(evaluate(r, r[-1].ts + timedelta(seconds=1), CFG, "Alex", symptom).hit_types)


def test_flat_trace_predicts_flat() -> None:
    fc = forecast([120, 120, 120, 120])
    assert fc is not None
    assert (fc.predicted, fc.slope_per_5min, fc.horizon_min) == (120, 0.0, 20)


def test_falling_trace_projects_twenty_minutes_ahead() -> None:
    fc = forecast([110, 104, 98, 92])  # -6 per reading
    assert fc is not None
    assert fc.slope_per_5min == -6.0
    assert fc.predicted == 68  # 92 - 4*6
    assert fc.r2 == 1.0


def test_noisy_trace_has_lower_confidence_and_clamped_range() -> None:
    noisy = forecast([120, 135, 110, 128])
    assert noisy is not None and noisy.r2 < 0.5
    crash = forecast([90, 70, 50, 41])
    assert crash is not None and crash.predicted == 40  # clamped to sensor range


def test_too_few_readings_gives_no_forecast() -> None:
    assert forecast([120, 118]) is None


def test_predicted_low_warns_before_the_threshold() -> None:
    hits = hit_types([110, 104, 98, 92])
    assert "predicted_low" in hits
    assert "low" not in hits, "still above 70: only the forecast rule fires"


def test_predicted_urgent_low_replaces_predicted_low() -> None:
    hits = hit_types([120, 104, 88, 72])  # -16 per reading -> ~8 in 20 min
    assert "predicted_urgent_low" in hits
    assert "predicted_low" not in hits


def test_no_prediction_alerts_once_already_low() -> None:
    hits = hit_types([90, 80, 70, 60])
    assert not hits & {"predicted_low", "predicted_urgent_low"}
    ev = evaluate(trace(90, 80, 70, 60), T0 + timedelta(seconds=16), CFG, "Alex")
    assert "predicted_low" not in ev.evaluated, "left alone, not auto-resolved, while low"


def test_rising_trace_never_predicts_low() -> None:
    assert not hit_types([70, 80, 90, 100]) & {"predicted_low", "predicted_urgent_low"}


def test_symptoms_with_falling_glucose_escalate() -> None:
    shaky = Symptom("shaky", T0)
    assert "symptoms_reported" in hit_types([110, 104, 98, 92], shaky)
    assert "symptoms_reported" in hit_types([75, 76, 75, 76], shaky), "near low counts"
    assert "symptoms_reported" not in hit_types([140, 141, 140, 142], shaky), "steady and in range"


@pytest.fixture
async def child(engine: AsyncEngine, redis: Redis) -> AsyncIterator[uuid.UUID]:
    await redis.flushdb()
    cid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO children (id, first_name, age_band) VALUES (:c, 'Alex', '8-10')"),
            {"c": cid},
        )
    await save_state(redis, SimState())
    yield cid
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM glucose_readings WHERE child_id = :c"), {"c": cid})
        await conn.execute(text("DELETE FROM children WHERE id = :c"), {"c": cid})


async def test_forecasts_are_stored_and_scored(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    rng = random.Random(3)
    now = datetime.now(UTC).replace(microsecond=0)
    await set_scenario(redis, Scenario.DRIFT_LOW)
    for i in range(14):
        await run_tick(
            engine, redis, settings, child, "Alex", rng, now=now + timedelta(seconds=5 * i)
        )
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT count(*) AS n, count(error) AS scored, avg(abs(error)) AS mae
                       FROM forecasts WHERE child_id = :c"""
                ),
                {"c": child},
            )
        ).one()
    assert rows.n >= 10
    assert rows.scored >= 5, "forecasts whose 20-minute target has passed get scored"
    assert rows.mae is not None and float(rows.mae) < 25
