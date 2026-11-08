"""Child companion chat."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from sugarscout.ai.chat import handle_message
from sugarscout.api.deps import DemoKey, EngineDep, RedisDep, SettingsDep, deliver_now
from sugarscout.demo import DEMO_CHILD_ID

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class ChatOut(BaseModel):
    reply: str
    flagged: str | None
    escalated: bool
    emotion: str = "neutral"


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    flagged: str | None
    created_at: datetime


@router.get("/history", response_model=list[MessageOut])
async def history(engine: EngineDep) -> list[MessageOut]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT * FROM (
                         SELECT id, role, content, flagged, created_at FROM chat_messages
                         WHERE child_id = :c ORDER BY created_at DESC, id DESC LIMIT 40
                       ) recent ORDER BY created_at, id"""
                ),
                {"c": DEMO_CHILD_ID},
            )
        ).all()
    return [MessageOut.model_validate(r._mapping) for r in rows]


@router.post("", response_model=ChatOut, dependencies=[DemoKey])
async def chat(
    body: ChatIn, request: Request, engine: EngineDep, redis: RedisDep, settings: SettingsDep
) -> ChatOut:
    result = await handle_message(
        engine,
        redis,
        settings,
        request.app.state.llm,
        DEMO_CHILD_ID,
        settings.demo_child_name,
        body.message,
    )
    await deliver_now(request, result.sms_ids)
    return ChatOut(
        reply=result.reply,
        flagged=result.flagged,
        escalated=result.escalated,
        emotion=result.emotion,
    )
