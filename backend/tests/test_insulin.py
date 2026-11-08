"""Insulin log (record-only) and the demo simulator's meal/insulin effects."""

from __future__ import annotations

import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.api.main import create_app
from sugarscout.demo import DEMO_CHILD_ID, ensure_demo_child
from sugarscout.settings import Settings
from sugarscout.sim.cgm import EFFECTS_KEY, SimState, apply_effect, step


@pytest.fixture
async def api(settings: Settings, engine: AsyncEngine, redis: Redis) -> AsyncIterator[AsyncClient]:
    await redis.flushdb()
    await ensure_demo_child(engine, settings)
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM insulin_doses WHERE child_id = :c"), {"c": DEMO_CHILD_ID}
        )


async def test_parent_logs_a_dose_and_sees_it(api: AsyncClient, redis: Redis) -> None:
    r = await api.post("/insulin", json={"kind": "meal", "units": "3.5", "note": "lunch"})
    assert r.status_code == 200, r.text
    doses = (await api.get("/insulin")).json()
    assert doses[0]["units"] == "3.50" and doses[0]["source"] == "parent"
    assert await redis.llen(EFFECTS_KEY) == 1, "the demo simulator is told about the dose"


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "meal", "units": 150},
        {"kind": "meal", "units": -1},
        {"kind": "bolus?"},
        {"kind": "meal", "given_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()},
    ],
)
async def test_invalid_doses_are_rejected(api: AsyncClient, body: dict[str, object]) -> None:
    assert (await api.post("/insulin", json=body)).status_code == 422


async def test_units_are_optional(api: AsyncClient) -> None:
    assert (await api.post("/insulin", json={"kind": "correction"})).status_code == 200


def _run(state: SimState, n: int, rng: random.Random) -> list[int]:
    return [v for _ in range(n) if (v := step(state, rng)) is not None]


def test_meal_without_insulin_rises_and_stays_up() -> None:
    rng = random.Random(1)
    state = SimState(value=120)
    _run(state, 5, rng)
    apply_effect(state, "meal", carbs_g=54)
    after = _run(state, 20, rng)
    assert max(after) > 220
    assert after[-1] > 200, "no insulin: it stays high"


def test_insulin_flattens_a_meal_rise() -> None:
    rng_a, rng_b = random.Random(2), random.Random(2)
    no_insulin, with_insulin = SimState(value=120), SimState(value=120)
    for s in (no_insulin, with_insulin):
        apply_effect(s, "meal", carbs_g=54)
    _run(no_insulin, 4, rng_a)
    _run(with_insulin, 4, rng_b)
    apply_effect(with_insulin, "insulin")
    end_a = _run(no_insulin, 24, rng_a)[-1]
    end_b = _run(with_insulin, 24, rng_b)[-1]
    assert end_b < end_a - 60
    assert end_b < 170
