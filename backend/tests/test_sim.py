"""Simulation harness: drive the fake CGM through demo scenarios and assert the exact
alert lifecycle (Section 12), including dedupe, auto-resolve, cooldown, and SMS fan-out."""

from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.notify.sms import deliver
from sugarscout.settings import Settings
from sugarscout.sim.cgm import Scenario, SimState, save_state, set_scenario, step
from sugarscout.sim.tick import run_tick

NAME = "Alex"


@pytest.fixture
async def child(engine: AsyncEngine, redis: Redis) -> AsyncIterator[uuid.UUID]:
    await redis.flushdb()
    cid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO children (id, first_name, age_band) VALUES (:c, :n, '8-10')"),
            {"c": cid, "n": NAME},
        )
    await save_state(redis, SimState())
    yield cid
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM glucose_readings WHERE child_id = :c"), {"c": cid})
        await conn.execute(text("DELETE FROM children WHERE id = :c"), {"c": cid})


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC).replace(microsecond=0)

    def tick(self, seconds: int = 5) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


async def run(
    engine: AsyncEngine, redis: Redis, settings: Settings, cid: uuid.UUID, clock: Clock, n: int
) -> tuple[list[tuple[str, str]], list[int]]:
    rng = random.Random(7)
    events: list[tuple[str, str]] = []
    sms: list[int] = []
    for _ in range(n):
        _, evs, ids = await run_tick(engine, redis, settings, cid, NAME, rng, now=clock.tick())
        events += [(e.rule_type, e.kind) for e in evs]
        sms += ids
    return events, sms


async def alerts(engine: AsyncEngine, cid: uuid.UUID) -> list[tuple[str, str]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT rule_type, state FROM alerts WHERE child_id = :c ORDER BY id"),
                {"c": cid},
            )
        ).all()
    return [(r.rule_type, r.state) for r in rows]


def test_rapid_drop_reaches_urgent_low_in_about_30_seconds() -> None:
    state = SimState(scenario=Scenario.RAPID_DROP)
    rng = random.Random(1)
    ticks = 0
    while (v := step(state, rng)) is not None and v >= 54:
        ticks += 1
    assert 4 <= ticks <= 8  # 5-second ticks: ~20-40 s


async def test_steady_produces_no_alerts(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    events, sms = await run(engine, redis, settings, child, Clock(), 12)
    assert events == []
    assert sms == []


async def test_rapid_drop_then_recover_lifecycle(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    clock = Clock()
    await run(engine, redis, settings, child, clock, 4)  # establish a steady baseline
    await set_scenario(redis, Scenario.RAPID_DROP)
    drop_events, sms = await run(engine, redis, settings, child, clock, 12)

    opened = [r for r, k in drop_events if k == "opened"]
    assert {"rapid_drop", "low", "urgent_low"} <= set(opened)
    assert opened.count("urgent_low") == 1, "an episode must open once, not every tick"
    assert len(sms) == 1, "only urgent_low texts on open"

    await set_scenario(redis, Scenario.RECOVER)
    events, sms = await run(engine, redis, settings, child, clock, 20)
    # rapid_drop may clear while the value is still bottoming out, before the recovery.
    resolved = {r for r, k in drop_events + events if k == "resolved"}
    assert {"urgent_low", "low", "rapid_drop"} <= resolved
    assert len(sms) == 1, "resolve SMS only for the alert that texted on open"
    assert all(state == "resolved" for _, state in await alerts(engine, child))


async def test_dropout_opens_data_gap_and_freezes_value_rules(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    clock = Clock()
    await set_scenario(redis, Scenario.RAPID_DROP)
    await run(engine, redis, settings, child, clock, 10)
    await set_scenario(redis, Scenario.DROPOUT)
    events, sms = await run(engine, redis, settings, child, clock, 8)  # 40 s of silence

    assert ("data_gap", "opened") in events
    assert not [e for e in events if e[1] == "resolved"], "silence must not resolve the low"
    assert len(sms) == 1

    await set_scenario(redis, Scenario.RECOVER)
    events, _ = await run(engine, redis, settings, child, clock, 1)
    assert ("data_gap", "resolved") in events


async def test_sms_cooldown_suppresses_repeat_episodes(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    clock = Clock()
    for _ in range(2):
        await set_scenario(redis, Scenario.RAPID_DROP)
        await run(engine, redis, settings, child, clock, 10)
        await set_scenario(redis, Scenario.RECOVER)
        await run(engine, redis, settings, child, clock, 20)

    async with engine.connect() as conn:
        statuses = (
            (
                await conn.execute(
                    text(
                        """SELECT n.status FROM notifications n JOIN alerts a ON a.id = n.alert_id
                       WHERE a.child_id = :c AND a.rule_type = 'urgent_low'
                         AND n.channel = 'sms' AND n.kind = 'opened' ORDER BY n.id"""
                    ),
                    {"c": child},
                )
            )
            .scalars()
            .all()
        )
    assert statuses == ["queued", "skipped"]


async def test_sms_without_twilio_is_dry_run(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    clock = Clock()
    await set_scenario(redis, Scenario.RAPID_DROP)
    _, sms = await run(engine, redis, settings, child, clock, 10)
    assert settings.twilio_configured is False
    assert await deliver(engine, settings, sms[0]) == "dry_run"
    assert await deliver(engine, settings, sms[0]) == "noop", "never delivered twice"
