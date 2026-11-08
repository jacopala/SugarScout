"""Concern weighting: deterministic scoring of a child's message, and what it triggers."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.ai.chat import handle_message
from sugarscout.ai.concern import CALL_SUGGESTION, assess, from_mood
from sugarscout.ai.safety import detect_emergency
from sugarscout.settings import Settings
from tests.test_chat import FakeModel


@pytest.mark.parametrize(
    ("message", "level"),
    [
        ("tell me a joke", "none"),
        ("I had a snack", "none"),
        ("I'm not sad, I'm happy", "none"),
        ("it doesn't hurt anymore", "none"),
        ("I'm a bit angry", "mild"),
        ("I feel sad", "mild"),
        ("I'm really sad", "moderate"),
        ("my tummy hurts and I'm worried", "moderate"),
        ("I want my mom", "moderate"),
        ("i feel shaky", "moderate"),
        ("I'm scared and I want my dad", "high"),
        ("kids were mean to me and now I'm crying", "moderate"),
        ("I feel sick and my head hurts so much", "high"),
    ],
)
def test_levels(message: str, level: str) -> None:
    assert assess(message).level == level, assess(message)


def test_body_worries_weigh_more_while_glucose_is_low() -> None:
    calm = assess("I feel weird")
    low = assess("I feel weird", glucose_low_or_falling=True)
    assert calm.level == "mild"
    assert low.level == "moderate"
    assert "while glucose is low or falling" in low.signals
    # Feelings alone don't get the glucose bonus.
    assert assess("I'm sad", glucose_low_or_falling=True).score == assess("I'm sad").score


def test_each_signal_counts_once_and_labels_are_readable() -> None:
    c = assess("sad sad sad")
    assert c.score == 2
    assert c.signals == ["sad"]


def test_levels_map_to_actions() -> None:
    assert not assess("I feel sad").suggest_call
    assert assess("I want my mom").suggest_call
    assert not assess("I want my mom").notify_parent
    assert assess("I'm scared and I want my dad").notify_parent


def test_mood_check_in() -> None:
    assert from_mood(1).suggest_call
    assert from_mood(2).level == "mild"
    assert not from_mood(2).suggest_call
    assert from_mood(5).level == "none"


def test_emergencies_are_still_caught_first() -> None:
    # Severe phrases never reach the concern scorer: the emergency bypass handles them.
    assert detect_emergency("I feel really dizzy and shaky") is not None


@pytest.fixture
async def child(engine: AsyncEngine, redis: Redis) -> AsyncIterator[uuid.UUID]:
    await redis.flushdb()
    cid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO children (id, first_name, age_band) VALUES (:c, 'Alex', '8-10')"),
            {"c": cid},
        )
    yield cid
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM children WHERE id = :c"), {"c": cid})


async def _alerts(engine: AsyncEngine, child: uuid.UUID) -> list[tuple[str, str]]:
    async with engine.connect() as conn:
        return [
            (r.rule_type, r.severity)
            for r in await conn.execute(
                text("SELECT rule_type, severity FROM alerts WHERE child_id = :c"), {"c": child}
            )
        ]


async def test_moderate_concern_suggests_a_call_without_alerting(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    model = FakeModel(reply="[happy] I'm here with you.")
    r = await handle_message(engine, redis, settings, model, child, "Alex", "I want my mom")
    assert r.concern.level == "moderate"
    assert r.reply.endswith(CALL_SUGGESTION)
    assert r.emotion == "calm", "never cheerful while a child is worried"
    assert "sounds asking for a grown-up" in model.calls[-1][0]["content"]
    assert await _alerts(engine, child) == []


async def test_high_concern_also_gives_the_parent_a_heads_up(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    r = await handle_message(
        engine, redis, settings, FakeModel(), child, "Alex", "I'm scared and I want my dad"
    )
    assert r.concern.notify_parent
    assert r.reply.endswith(CALL_SUGGESTION)
    assert r.sms_ids == [], "a worried-words heads-up is push and dashboard, not SMS"
    assert await _alerts(engine, child) == [("child_concern", "warning")]


async def test_call_is_suggested_even_when_the_ai_is_off_or_down(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    off = await handle_message(engine, redis, settings, None, child, "Alex", "I want my mom")
    down = await handle_message(
        engine, redis, settings, FakeModel(fail=True), child, "Alex", "I really need my dad"
    )
    assert off.reply.endswith(CALL_SUGGESTION)
    assert down.reply.endswith(CALL_SUGGESTION)


async def test_ordinary_chat_is_unchanged(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    r = await handle_message(engine, redis, settings, FakeModel(), child, "Alex", "tell me a joke")
    assert r.concern.level == "none"
    assert r.reply == "Hi Alex! How was school?"


async def test_endpoints_offer_the_call_with_the_guardian_number(
    engine: AsyncEngine, redis: Redis, settings: Settings
) -> None:
    from httpx import ASGITransport, AsyncClient

    from sugarscout.api.main import create_app
    from sugarscout.demo import DEMO_CHILD_ID, ensure_demo_child

    await redis.flushdb()
    await ensure_demo_child(engine, settings)
    app = create_app(
        settings.model_copy(update={"parent_phone": "+15550100", "nvidia_api_key": ""})
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        worried = (await c.post("/chat", json={"message": "I want my mom"})).json()
        fine = (await c.post("/chat", json={"message": "tell me a joke"})).json()
        sad = (await c.post("/checkins", json={"mood": 1})).json()
        happy = (await c.post("/checkins", json={"mood": 5})).json()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM alerts WHERE child_id = :c"), {"c": DEMO_CHILD_ID})

    assert worried["suggest_call"] and worried["guardian_phone"] == "+15550100"
    assert worried["concern_level"] == "moderate"
    assert not fine["suggest_call"] and fine["guardian_phone"] is None, "number only when needed"
    assert sad["suggest_call"] and sad["guardian_phone"] == "+15550100"
    assert not happy["suggest_call"] and happy["guardian_phone"] is None


async def test_model_cannot_talk_over_the_call_offer(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    from sugarscout.ai.chat import CONCERN_ACK

    chatty = FakeModel(
        reply="[calm] I understand you want your mom. The app can call her if you like. "
        "Or tell her yourself!"
    )
    r = await handle_message(engine, redis, settings, chatty, child, "Alex", "I want my mom")
    assert r.reply == f"I understand you want your mom. {CALL_SUGGESTION}", "the rest is dropped"

    caller = FakeModel(reply="[calm] I can call your mom for you right now!")
    r = await handle_message(engine, redis, settings, caller, child, "Alex", "I want my mom")
    assert r.reply == f"{CONCERN_ACK} {CALL_SUGGESTION}", "model's own call talk is replaced"

    kind = FakeModel(reply="[calm] Missing your mom is a big feeling. Want to play a game?")
    r = await handle_message(engine, redis, settings, kind, child, "Alex", "I want my mom")
    assert r.reply == f"Missing your mom is a big feeling. {CALL_SUGGESTION}", "one sentence only"
