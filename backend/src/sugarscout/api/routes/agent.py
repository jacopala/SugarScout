"""Scout agent API: the child's pending question, answers, and the parent's timeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from sugarscout.agent.agent import run_agent
from sugarscout.agent.answers import AnswerError, answer_question, pending_question
from sugarscout.agent.questions import BANK
from sugarscout.api.deps import DemoKey, EngineDep, RedisDep, SettingsDep, enqueue
from sugarscout.demo import DEMO_CHILD_ID

router = APIRouter(prefix="/agent", tags=["agent"])


class Option(BaseModel):
    value: str
    label: str


class QuestionOut(BaseModel):
    id: int
    question: str
    kind: str
    wording: str
    options: list[Option]
    asked_at: datetime


class AnswerIn(BaseModel):
    question_id: int
    answer: str = Field(min_length=1, max_length=40)


class AnswerOut(BaseModel):
    reply: str
    emotion: str
    open_meals: bool


class TimelineItem(BaseModel):
    at: datetime
    type: str  # asked | heads_up
    text: str
    reasons: list[str]
    answer: str | None = None
    answered_at: datetime | None = None
    state: str | None = None


@router.get("/question", response_model=QuestionOut | None)
async def get_question(engine: EngineDep) -> QuestionOut | None:
    row = await pending_question(engine, DEMO_CHILD_ID)
    if row is None:
        return None
    return QuestionOut(
        id=row["id"],
        question=row["question"],
        kind=BANK[row["question"]].kind,
        wording=row["wording"],
        options=[Option(**o) for o in row["options"]],
        asked_at=row["asked_at"],
    )


@router.post("/answer", response_model=AnswerOut, dependencies=[DemoKey])
async def post_answer(
    body: AnswerIn, request: Request, engine: EngineDep, redis: RedisDep, settings: SettingsDep
) -> AnswerOut:
    try:
        result = await answer_question(
            engine, redis, settings, DEMO_CHILD_ID, body.question_id, body.answer
        )
    except AnswerError as exc:
        raise HTTPException(409, str(exc)) from exc
    for nid in result.sms_ids:
        await enqueue(request, "send_sms", nid)
    await enqueue(request, "agent_tick")
    return AnswerOut(reply=result.reply, emotion=result.emotion, open_meals=result.open_meals)


@router.post("/run", dependencies=[DemoKey])
async def run_now(
    request: Request, engine: EngineDep, redis: RedisDep, settings: SettingsDep
) -> dict[str, Any]:
    """Run one agent step now (the worker also runs it every 15 s)."""
    d, sms = await run_agent(
        engine, redis, settings, request.app.state.llm, DEMO_CHILD_ID, datetime.now(UTC)
    )
    for nid in sms:
        await enqueue(request, "send_sms", nid)
    return {"status": d.status, "ask": d.ask, "heads_up": d.heads_up, "overrides": d.overrides}


@router.get("/timeline", response_model=list[TimelineItem])
async def timeline(engine: EngineDep) -> list[TimelineItem]:
    async with engine.connect() as conn:
        asked = (
            await conn.execute(
                text(
                    """SELECT asked_at, question, wording, reasons, answer, answered_at, options
                       FROM agent_questions WHERE child_id = :c
                       ORDER BY asked_at DESC LIMIT 20"""
                ),
                {"c": DEMO_CHILD_ID},
            )
        ).all()
        heads = (
            await conn.execute(
                text(
                    """SELECT opened_at, message, trigger_data, state FROM alerts
                       WHERE child_id = :c AND rule_type = 'agent_heads_up'
                       ORDER BY opened_at DESC LIMIT 10"""
                ),
                {"c": DEMO_CHILD_ID},
            )
        ).all()
    items = [
        TimelineItem(
            at=r.asked_at,
            type="asked",
            text=r.wording,
            reasons=list(r.reasons or []),
            answer=next((o["label"] for o in r.options if o["value"] == r.answer), r.answer),
            answered_at=r.answered_at,
        )
        for r in asked
    ] + [
        TimelineItem(
            at=r.opened_at,
            type="heads_up",
            text=r.message,
            reasons=list((r.trigger_data or {}).get("reasons", [])),
            state=r.state,
        )
        for r in heads
    ]
    return sorted(items, key=lambda i: i.at, reverse=True)[:20]
