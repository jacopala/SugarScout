"""Help button and meal logging (model and speech faked; no network)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.ai.meals import CHILD_MEAL_REPLY, analyze_meal, record_meal
from sugarscout.ai.summary import compute_stats
from sugarscout.api.main import create_app
from sugarscout.demo import DEMO_CHILD_ID, ensure_demo_child
from sugarscout.settings import Settings
from tests.test_chat import FakeModel
from tests.test_voice import CLIP, FakeSpeech

GOOD = {
    "items": [
        {"name": "turkey sandwich", "sugar_g": 4, "contains_gluten": True},
        {"name": "apple juice", "sugar_g": 22, "contains_gluten": False},
    ],
    "confidence": "medium",
    "note": "Most of the sugar is from the juice.",
}


@pytest.fixture
async def api(
    settings: Settings, engine: AsyncEngine, redis: Redis
) -> AsyncIterator[tuple[AsyncClient, object]]:
    await redis.flushdb()
    await ensure_demo_child(engine, settings)
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c, app
    async with engine.begin() as conn:
        for table in ("meals", "alerts", "glucose_readings"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE child_id = :c"), {"c": DEMO_CHILD_ID}
            )


async def test_help_button_opens_urgent_alert_with_sms_once(
    api: tuple[AsyncClient, object], engine: AsyncEngine
) -> None:
    c, _ = api
    first = (await c.post("/help")).json()
    second = (await c.post("/help")).json()
    assert first["sent"] and not first["already_open"]
    assert second["already_open"], "pressing again doesn't send another text"

    async with engine.connect() as conn:
        alert = (
            await conn.execute(
                text(
                    """SELECT a.id, a.severity, a.state,
                              (SELECT count(*) FROM notifications n
                                WHERE n.alert_id = a.id AND n.channel = 'sms') AS sms
                       FROM alerts a WHERE a.child_id = :c AND a.rule_type = 'help_request'"""
                ),
                {"c": DEMO_CHILD_ID},
            )
        ).one()
    assert (alert.severity, alert.state, alert.sms) == ("urgent", "open", 1)

    status = (await c.get("/child/status")).json()
    assert status["reminder_rule"] == "help_request"

    acked = (await c.post(f"/alerts/{alert.id}/ack")).json()
    assert acked["state"] == "resolved", "a parent acknowledgement closes a help request"


async def test_meal_post_is_instant_and_child_sees_no_numbers(
    api: tuple[AsyncClient, object],
) -> None:
    c, _ = api
    r = await c.post(
        "/meals", json={"description": "turkey sandwich and apple juice", "source": "voice"}
    )
    assert r.status_code == 200
    assert r.json()["reply"] == CHILD_MEAL_REPLY
    meals = (await c.get("/meals")).json()
    assert meals[0]["analysis_status"] == "pending"
    assert meals[0]["source"] == "voice"


async def test_meal_analysis_totals_and_glucose_after(
    engine: AsyncEngine, settings: Settings, api: tuple[AsyncClient, object]
) -> None:
    c, _ = api
    meal_id = await record_meal(engine, DEMO_CHILD_ID, "turkey sandwich and apple juice", "voice")
    async with engine.begin() as conn:
        created = (
            await conn.execute(text("SELECT created_at FROM meals WHERE id = :i"), {"i": meal_id})
        ).scalar_one()
        await conn.execute(
            text(
                """INSERT INTO glucose_readings (child_id, ts, value_mg_dl, source)
                   VALUES (:c, :ts, 168, 'test')"""
            ),
            {"c": DEMO_CHILD_ID, "ts": created + timedelta(minutes=58)},
        )
    assert await analyze_meal(engine, settings, FakeModel(reply=json.dumps(GOOD)), meal_id) == "ok"

    meal = next(m for m in (await c.get("/meals")).json() if m["id"] == meal_id)
    assert meal["analysis"]["total_sugar_g"] == 26
    assert meal["analysis"]["contains_gluten"] is True
    assert meal["glucose_1h"] == 168

    stats = await compute_stats(engine, DEMO_CHILD_ID)
    assert stats["meals_logged"] >= 1 and stats["meals_with_gluten"] >= 1


@pytest.mark.parametrize(
    ("reply", "status"),
    [
        (json.dumps({**GOOD, "note": "Give 2 units of insulin for the juice."}), "rejected"),
        ("I think it was yummy!", "rejected"),
        (
            json.dumps(
                {**GOOD, "items": [{"name": "cake", "sugar_g": 9999, "contains_gluten": True}]}
            ),
            "rejected",
        ),
    ],
)
async def test_unsafe_or_invalid_estimates_are_rejected(
    engine: AsyncEngine,
    settings: Settings,
    api: tuple[AsyncClient, object],
    reply: str,
    status: str,
) -> None:
    meal_id = await record_meal(engine, DEMO_CHILD_ID, "cake", "tap")
    assert await analyze_meal(engine, settings, FakeModel(reply=reply), meal_id) == status


async def test_meal_without_model_is_kept_but_not_estimated(
    engine: AsyncEngine, settings: Settings, api: tuple[AsyncClient, object]
) -> None:
    meal_id = await record_meal(engine, DEMO_CHILD_ID, "pasta", "text")
    assert await analyze_meal(engine, settings, None, meal_id) == "disabled"
    assert await analyze_meal(engine, settings, None, meal_id) == "noop", "analyzed once"


async def test_dictation_returns_transcript_without_wake_word(
    api: tuple[AsyncClient, object],
) -> None:
    c, app = api
    app.state.speech = FakeSpeech("a turkey sandwich and apple juice")  # type: ignore[attr-defined]
    r = await c.post("/voice/transcribe", content=CLIP)
    assert r.json() == {"transcript": "a turkey sandwich and apple juice"}
