"""Chat pipeline: emergency bypass, output filter, fallbacks, and context. Model mocked."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.ai.chat import AI_OFF_REPLY, MODEL_DOWN_REPLY, handle_message
from sugarscout.ai.safety import SAFE_FALLBACK, SCRIPTED_REPLIES, check_output, detect_emergency
from sugarscout.api.main import create_app
from sugarscout.demo import DEMO_CHILD_ID, ensure_demo_child
from sugarscout.settings import Settings


class FakeModel:
    def __init__(self, reply: str = "Hi Alex! How was school?", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool = False,
    ) -> str:
        self.calls.append(messages)
        if self.fail:
            raise TimeoutError("model timed out")
        return self.reply


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


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("I feel really dizzy and shaky", "symptoms"),
        ("i cant breathe good", "symptoms"),
        ("I think I'm going to pass out", "symptoms"),
        ("sometimes i want to die", "self_harm"),
        ("my uncle hits me", "abuse"),
    ],
)
def test_emergency_phrases_are_detected(message: str, category: str) -> None:
    match = detect_emergency(message)
    assert match is not None
    assert match.category == category


@pytest.mark.parametrize(
    "message", ["I feel shaky", "I had a snack", "I'm dying to play outside lol", "hi scout!"]
)
def test_ordinary_messages_are_not_emergencies(message: str) -> None:
    # "dying to" is an idiom; only "want to die" style phrases match.
    assert detect_emergency(message) is None


@pytest.mark.parametrize(
    "reply",
    [
        "You should take 2 units of insulin now.",
        "Maybe increase your insulin dose a little.",
        "It sounds like you have DKA.",
        "What's your address?",
        "Your carb ratio might be off.",
    ],
)
def test_unsafe_model_output_is_caught(reply: str) -> None:
    assert check_output(reply) is not None


@pytest.mark.parametrize(
    "reply",
    [
        "Yum, apple slices are a great snack! What else did you do today?",
        "Your plan says it's time for your fast sugar snack. Can you tell a grown-up?",
    ],
)
def test_friendly_output_passes(reply: str) -> None:
    assert check_output(reply) is None


async def test_emergency_bypasses_model_and_escalates(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    model = FakeModel()
    result = await handle_message(
        engine, redis, settings, model, child, "Alex", "I feel really dizzy and shaky"
    )
    assert model.calls == [], "the model must never see an emergency message"
    assert result.reply == SCRIPTED_REPLIES["symptoms"]
    assert result.escalated and result.flagged == "emergency"
    assert len(result.sms_ids) == 1
    async with engine.connect() as conn:
        alert = (
            await conn.execute(
                text("SELECT rule_type, severity, state FROM alerts WHERE child_id = :c"),
                {"c": child},
            )
        ).one()
    assert tuple(alert) == ("emergency_language", "urgent", "open")


async def test_normal_message_uses_model_with_persona_and_reminder(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO alerts (child_id, rule_type, severity, message)
                   VALUES (:c, 'low', 'warning', 'low')"""
            ),
            {"c": child},
        )
    model = FakeModel()
    await handle_message(engine, redis, settings, model, child, "Alex", "hi scout")
    result = await handle_message(engine, redis, settings, model, child, "Alex", "I had a snack")

    assert result.reply == "Hi Alex! How was school?"
    system = model.calls[-1][0]["content"]
    assert "not a doctor" in system
    assert "fast sugar snack" in system, "active care-plan reminder is relayed"
    roles = [m["role"] for m in model.calls[-1]]
    assert roles == ["system", "user", "assistant", "user"], "history is included"


async def test_unsafe_reply_is_replaced(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    model = FakeModel(reply="Take 3 units of insulin.")
    result = await handle_message(engine, redis, settings, model, child, "Alex", "what do i do")
    assert result.reply == SAFE_FALLBACK
    assert result.flagged == "filtered"


async def test_model_failure_and_ai_off_degrade_gracefully(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    down = await handle_message(engine, redis, settings, FakeModel(fail=True), child, "Alex", "hi")
    assert down.reply == MODEL_DOWN_REPLY
    off = await handle_message(engine, redis, settings, None, child, "Alex", "hi")
    assert off.reply == AI_OFF_REPLY


async def test_chat_endpoint_requires_access_code_when_set(
    settings: Settings, engine: AsyncEngine, redis: Redis
) -> None:
    await ensure_demo_child(engine, settings)
    app = create_app(settings.model_copy(update={"demo_access_code": "letmein"}))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        app.state.llm = FakeModel()
        denied = await c.post("/chat", json={"message": "hi"})
        ok = await c.post("/chat", json={"message": "hi"}, headers={"X-Demo-Key": "letmein"})
        history = await c.get("/chat/history")
    assert denied.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["reply"] == "Hi Alex! How was school?"
    assert [m["role"] for m in history.json()][-2:] == ["child", "companion"]
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM chat_messages WHERE child_id = :c"), {"c": DEMO_CHILD_ID}
        )


async def test_flagged_turns_never_reach_the_model(
    engine: AsyncEngine, redis: Redis, settings: Settings, child: uuid.UUID
) -> None:
    await handle_message(engine, redis, settings, None, child, "Alex", "hi")  # AI-off fallback
    await handle_message(engine, redis, settings, FakeModel(), child, "Alex", "I feel really dizzy")
    model = FakeModel()
    await handle_message(engine, redis, settings, model, child, "Alex", "tell me a joke")
    sent = " ".join(m["content"] for m in model.calls[-1][1:])
    assert "dizzy" not in sent, "emergency text must never reach the model, even as history"
    assert AI_OFF_REPLY not in sent, "fallback lines must not be fed back to be imitated"
