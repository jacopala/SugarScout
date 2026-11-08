"""Scout agent: question policy, concern, guardrails, answers (model and speech faked)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.agent.agent import apply_guardrails, run_agent
from sugarscout.agent.questions import eligible, match_answer
from sugarscout.agent.situation import Situation, assess_concern
from sugarscout.api.main import create_app
from sugarscout.demo import DEMO_CHILD_ID, ensure_demo_child
from sugarscout.settings import Settings
from tests.test_chat import FakeModel
from tests.test_voice import CLIP, FakeSpeech


def sit(**kw: object) -> Situation:
    s = Situation(**{"child_name": "Alex", "glucose_stale": False, "checkin_today": True, **kw})  # type: ignore[arg-type]
    assess_concern(s)
    return s


# ---- question policy -------------------------------------------------------------------


def test_falling_glucose_asks_how_the_child_feels_first() -> None:
    s = sit(glucose=95, slope_per_5min=-6, forecast=71, forecast_horizon_min=20)
    assert next(e.id for e in eligible(s)) == "symptoms_now"


def test_uncovered_meal_with_rising_glucose_asks_about_insulin() -> None:
    s = sit(
        glucose=170,
        slope_per_5min=8,
        forecast=200,
        minutes_since_meal=20,
        meal_covered_by_insulin=False,
        last_meal_id=1,
    )
    assert "insulin_with_meal" in [e.id for e in eligible(s)]


def test_covered_meal_does_not_ask_about_insulin() -> None:
    s = sit(
        glucose=170,
        slope_per_5min=8,
        minutes_since_meal=20,
        meal_covered_by_insulin=True,
        last_meal_id=1,
    )
    assert "insulin_with_meal" not in [e.id for e in eligible(s)]


def test_moving_glucose_with_no_recent_meal_asks_when_they_ate() -> None:
    s = sit(glucose=215, slope_per_5min=4)
    assert "last_meal" in [e.id for e in eligible(s)]


def test_after_meal_mood_window() -> None:
    assert "after_meal_mood" in [
        e.id
        for e in eligible(sit(glucose=130, slope_per_5min=0, minutes_since_meal=60, last_meal_id=1))
    ]
    assert "after_meal_mood" not in [
        e.id
        for e in eligible(sit(glucose=130, slope_per_5min=0, minutes_since_meal=20, last_meal_id=1))
    ]


def test_daily_mood_only_when_steady_and_not_done() -> None:
    s = Situation(child_name="Alex", glucose=120, glucose_stale=False, slope_per_5min=0.5)
    assert [e.id for e in eligible(s)] == ["daily_mood"]


def test_one_question_at_a_time_and_cooldowns() -> None:
    assert eligible(sit(glucose=60, slope_per_5min=-5, pending_question="last_meal")) == []
    cooled = sit(glucose=60, slope_per_5min=-5, minutes_since_asked={"symptoms_now": 10})
    assert "symptoms_now" not in [e.id for e in eligible(cooled)]


def test_concern_levels() -> None:
    assert sit(glucose=120, slope_per_5min=0).concern == 0
    assert sit(glucose=95, slope_per_5min=-3, forecast=82, forecast_horizon_min=20).concern == 1
    rising = sit(
        glucose=210,
        slope_per_5min=9,
        minutes_since_meal=30,
        meal_covered_by_insulin=False,
        last_meal_carbs_g=54,
    )
    assert rising.concern == 2 and "no insulin logged" in rising.concern_reasons[0]


# ---- guardrails --------------------------------------------------------------------------

RISING = dict(
    glucose=210,
    slope_per_5min=9,
    minutes_since_meal=30,
    meal_covered_by_insulin=False,
    last_meal_carbs_g=54,
    last_meal_id=1,
)


def test_model_cannot_ask_a_question_that_is_not_allowed() -> None:
    s = sit(**RISING)
    d = apply_guardrails(
        {"ask": "daily_mood", "wording": "Hi!", "heads_up": {"send": False}}, s, eligible(s)
    )
    assert d.ask == "insulin_with_meal" and d.status == "overridden"


def test_heads_up_needs_concern() -> None:
    calm = sit(glucose=120, slope_per_5min=0, checkin_today=False)
    d = apply_guardrails(
        {"ask": None, "heads_up": {"send": True, "message": "All fine"}}, calm, eligible(calm)
    )
    assert d.heads_up is None and "heads-up not allowed now" in d.overrides


def test_unsafe_child_wording_and_parent_advice_are_replaced() -> None:
    s = sit(**RISING)
    d = apply_guardrails(
        {
            "ask": "insulin_with_meal",
            "wording": "Your glucose is 210 mg/dL, take 3 units!",
            "heads_up": {"send": True, "message": "Give Alex 3 units of insulin now."},
            "reasons": ["rising"],
        },
        s,
        eligible(s),
    )
    assert d.wording == "Did you have your insulin with your snack?"
    assert d.heads_up is not None and "units" not in d.heads_up
    assert "rising to 210" in d.heads_up


def test_safety_question_is_asked_even_if_model_says_none() -> None:
    s = sit(glucose=78, slope_per_5min=-6, forecast=54, forecast_horizon_min=20)
    d = apply_guardrails({"ask": None, "heads_up": {"send": False}}, s, eligible(s))
    assert d.ask == "symptoms_now"


def test_model_failure_falls_back_to_top_question_without_heads_up() -> None:
    s = sit(**RISING)
    d = apply_guardrails(None, s, eligible(s))
    assert d.status == "fallback" and d.ask == "insulin_with_meal" and d.heads_up is None


@pytest.mark.parametrize(
    ("qid", "said", "value"),
    [
        ("symptoms_now", "I feel kind of shaky", "shaky"),
        ("symptoms_now", "my tummy hurts", "tummy"),
        ("insulin_with_meal", "not yet", "not_yet"),
        ("insulin_with_meal", "yeah I did", "yes"),
        ("last_meal", "I just ate", "just_now"),
        ("after_meal_mood", "not great", "2"),
        ("after_meal_mood", "happy!", "5"),
        ("symptoms_now", "what's for dinner", None),
    ],
)
def test_spoken_answers_match_options(qid: str, said: str, value: str | None) -> None:
    assert match_answer(qid, said) == value


# ---- end to end -------------------------------------------------------------------------


@pytest.fixture
async def api(
    settings: Settings, engine: AsyncEngine, redis: Redis
) -> AsyncIterator[tuple[AsyncClient, object]]:
    await redis.flushdb()
    await ensure_demo_child(engine, settings)
    async with engine.begin() as conn:
        for table in (
            "agent_questions",
            "agent_decisions",
            "insulin_doses",
            "meals",
            "alerts",
            "glucose_readings",
            "mood_checkins",
        ):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE child_id = :c"), {"c": DEMO_CHILD_ID}
            )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c, app
    async with engine.begin() as conn:
        for table in (
            "agent_questions",
            "agent_decisions",
            "insulin_doses",
            "meals",
            "alerts",
            "glucose_readings",
            "mood_checkins",
        ):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE child_id = :c"), {"c": DEMO_CHILD_ID}
            )


async def _readings(engine: AsyncEngine, values: list[int], now: datetime) -> None:
    async with engine.begin() as conn:
        for i, v in enumerate(values):
            await conn.execute(
                text(
                    "INSERT INTO glucose_readings (child_id, ts, value_mg_dl, source) VALUES (:c, :ts, :v, 'test')"
                ),
                {
                    "c": DEMO_CHILD_ID,
                    "ts": now - timedelta(seconds=5 * (len(values) - 1 - i)),
                    "v": v,
                },
            )


async def test_snack_without_insulin_asks_child_and_heads_up_parent(
    api: tuple[AsyncClient, object], engine: AsyncEngine, redis: Redis, settings: Settings
) -> None:
    c, _ = api
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO meals (child_id, description, source, analysis_status, analysis, created_at)
                   VALUES (:c, 'juice box and two cookies', 'tap', 'ok',
                           '{"total_carbs_g": 54, "total_sugar_g": 38}', :at)"""
            ),
            {"c": DEMO_CHILD_ID, "at": now - timedelta(seconds=20)},
        )
    await _readings(engine, [150, 165, 182, 198, 214], now)
    model = FakeModel(
        reply=json.dumps(
            {
                "ask": "insulin_with_meal",
                "wording": "Hey Alex, did you have your insulin with your snack?",
                "heads_up": {
                    "send": True,
                    "message": "Alex is rising (214) after ~54 g carbs and no insulin is logged.",
                },
                "reasons": ["rising after a snack", "no insulin logged"],
            }
        )
    )
    d, _ = await run_agent(engine, redis, settings, model, DEMO_CHILD_ID, now)
    assert d.status == "ok" and d.ask == "insulin_with_meal" and d.heads_up

    q = (await c.get("/agent/question")).json()
    assert q["question"] == "insulin_with_meal" and q["wording"].startswith("Hey Alex")
    timeline = (await c.get("/agent/timeline")).json()
    assert {t["type"] for t in timeline} == {"asked", "heads_up"}

    async with engine.connect() as conn:
        channels = set(
            (
                await conn.execute(
                    text(
                        """SELECT n.channel FROM notifications n JOIN alerts a ON a.id = n.alert_id
                           WHERE a.rule_type = 'agent_heads_up' AND a.child_id = :c"""
                    ),
                    {"c": DEMO_CHILD_ID},
                )
            )
            .scalars()
            .all()
        )
    assert channels == {"dashboard", "push"}, "heads-ups never text: push and dashboard only"

    r = (await c.post("/agent/answer", json={"question_id": q["id"], "answer": "yes"})).json()
    assert r["reply"].startswith("Great job")
    doses = (await c.get("/insulin")).json()
    assert doses[0]["source"] == "child_report" and doses[0]["units"] is None
    assert (
        await c.post("/agent/answer", json={"question_id": q["id"], "answer": "yes"})
    ).status_code == 409


async def test_shaky_while_falling_escalates_with_the_childs_words(
    api: tuple[AsyncClient, object], engine: AsyncEngine, redis: Redis, settings: Settings
) -> None:
    c, _ = api
    now = datetime.now(UTC)
    await _readings(engine, [110, 102, 95, 88, 82], now)
    d, _ = await run_agent(engine, redis, settings, None, DEMO_CHILD_ID, now)
    assert d.ask == "symptoms_now" and d.status == "fallback"
    q = (await c.get("/agent/question")).json()
    r = (await c.post("/agent/answer", json={"question_id": q["id"], "answer": "shaky"})).json()
    assert "I've let your grown-up know" in r["reply"]
    alerts = (await c.get("/alerts")).json()
    sym = next(a for a in alerts if a["rule_type"] == "symptoms_reported")
    assert "said they feel shaky" in sym["message"] and sym["severity"] == "urgent"


async def test_spoken_answer_without_wake_word(
    api: tuple[AsyncClient, object], engine: AsyncEngine, redis: Redis, settings: Settings
) -> None:
    c, app = api
    now = datetime.now(UTC)
    await _readings(engine, [110, 102, 95, 88, 82], now)
    await run_agent(engine, redis, settings, None, DEMO_CHILD_ID, now)
    app.state.speech = FakeSpeech("I feel fine")  # type: ignore[attr-defined]
    data = (await c.post("/voice/turn", content=CLIP)).json()
    assert data["answered_question"] is True and data["reply"].startswith("Great")
    assert (await c.get("/agent/question")).json() is None


@pytest.mark.parametrize(
    "message",
    [
        "Alex is rising after a snack. Consider checking if insulin is needed.",
        "Alex needs insulin now.",
        "Consider giving a correction bolus.",
    ],
)
def test_heads_up_never_nudges_treatment(message: str) -> None:
    s = sit(**RISING)
    d = apply_guardrails(
        {"ask": None, "heads_up": {"send": True, "message": message}}, s, eligible(s)
    )
    assert d.heads_up is not None and "insulin is needed" not in d.heads_up
    assert "heads-up wording replaced" in d.overrides


def test_long_reasons_are_clipped_on_a_word_boundary() -> None:
    from sugarscout.agent.agent import REASON_MAX_CHARS, clip

    long = (
        "Glucose is 180 mg/dL and rising quickly so checking if Alex ate recently helps explain "
        * 3
    )
    out = clip(long)
    assert len(out) <= REASON_MAX_CHARS
    assert out.endswith("…")
    assert long.startswith(out[:-1])
    assert out[:-1] == out[:-1].rstrip()
    assert long[len(out) - 1] == " ", "cut falls between words, not mid-word"
    assert clip("short   reason\n") == "short reason"
