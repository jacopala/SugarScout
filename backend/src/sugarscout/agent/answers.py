"""Recording the child's answer to an agent question, and what follows from it.

Shared by the tap-to-answer buttons and spoken answers. Side effects are deterministic:
an insulin "yes" is recorded as a child report, moods are saved with their context, and
a symptom answer immediately re-runs the safety rules (which decide any urgent alert).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout import mood
from sugarscout.agent.questions import BANK
from sugarscout.settings import Settings
from sugarscout.sim.cgm import add_effect
from sugarscout.sim.tick import evaluate_and_sync


@dataclass(frozen=True)
class AnswerResult:
    reply: str
    emotion: str
    open_meals: bool
    sms_ids: list[int]


class AnswerError(ValueError):
    pass


async def pending_question(engine: AsyncEngine, child_id: uuid.UUID) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """SELECT id, question, wording, options, meal_id, asked_at
                       FROM agent_questions
                       WHERE child_id = :c AND answered_at IS NULL AND expires_at > now()
                       ORDER BY asked_at DESC LIMIT 1"""
                ),
                {"c": child_id},
            )
        ).first()
    return dict(row._mapping) if row else None


async def answer_question(
    engine: AsyncEngine,
    redis: Redis,
    settings: Settings,
    child_id: uuid.UUID,
    question_row_id: int,
    value: str,
) -> AnswerResult:
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """SELECT id, question, meal_id, answered_at FROM agent_questions
                       WHERE id = :id AND child_id = :c FOR UPDATE"""
                ),
                {"id": question_row_id, "c": child_id},
            )
        ).first()
        if row is None:
            raise AnswerError("No such question")
        if row.answered_at is not None:
            raise AnswerError("Already answered")
        q = BANK[row.question]
        if value not in {v for v, _ in q.options}:
            raise AnswerError("Not one of the options")
        await conn.execute(
            text("UPDATE agent_questions SET answer = :a, answered_at = now() WHERE id = :id"),
            {"a": value, "id": row.id},
        )
        if q.id == "insulin_with_meal" and value == "yes":
            await conn.execute(
                text(
                    """INSERT INTO insulin_doses (child_id, given_at, kind, source, note)
                       VALUES (:c, now(), 'meal', 'child_report', 'Child said yes when Scout asked')"""
                ),
                {"c": child_id},
            )

    sms: list[int] = []
    reply, emotion, open_meals = "Thanks for telling me!", "happy", False

    if q.kind == "mood":
        level = int(value)
        context = "after_meal" if q.id == "after_meal_mood" else "agent"
        await mood.record(engine, child_id, level, "tap", context, row.meal_id)
        reply, emotion = mood.MOOD_REPLIES[level], mood.MOOD_EMOTIONS[level]
    elif q.id == "symptoms_now":
        if value == "fine":
            reply, emotion = "Great! Thanks for telling me.", "happy"
        else:
            # The safety rules decide whether this is urgent (symptom + low/falling glucose).
            events, sms = await evaluate_and_sync(
                engine, redis, settings, child_id, settings.demo_child_name, datetime.now(UTC)
            )
            escalated = any(e.rule_type == "symptoms_reported" for e in events)
            if escalated:
                reply = (
                    "Thanks for telling me. I've let your grown-up know. "
                    "Please sit down and follow your plan."
                )
            else:
                reply = "Thanks for telling me. If you keep feeling that way, tell a grown-up."
            emotion = "calm"
    elif q.id == "insulin_with_meal":
        if value == "yes":
            await add_effect(redis, "insulin")  # demo simulator only
            reply, emotion = "Great job! Thanks for telling me.", "happy"
        elif value == "not_yet":
            reply, emotion = (
                "Okay, thanks for telling me. Let's check your plan with a grown-up.",
                "calm",
            )
        else:
            reply, emotion = "That's okay! Let's ask a grown-up together.", "calm"
    elif q.id == "last_meal":
        if value == "just_now":
            reply, emotion, open_meals = "Yum! Can you tell me what you ate?", "happy", True
        elif value == "not_today":
            reply, emotion = (
                "Thanks for telling me. Let's tell a grown-up you haven't eaten.",
                "calm",
            )
        else:
            reply, emotion = "Thanks for telling me!", "neutral"

    return AnswerResult(reply, emotion, open_meals, sms)
