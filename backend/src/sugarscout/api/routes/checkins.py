"""Mood check-ins: the child's landing question, and the parent's history view."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from sugarscout import mood
from sugarscout.ai.concern import from_mood
from sugarscout.api.deps import DemoKey, EngineDep, SettingsDep, concern_fields
from sugarscout.demo import DEMO_CHILD_ID

router = APIRouter(prefix="/checkins", tags=["checkins"])


class CheckinIn(BaseModel):
    mood: int = Field(ge=1, le=5)
    source: Literal["tap", "voice"] = "tap"
    context: Literal["daily", "after_meal", "agent"] = "daily"


class CheckinOut(BaseModel):
    id: int
    mood: int
    label: str
    source: str
    context: str = "daily"
    created_at: datetime


class CheckinCreated(CheckinOut):
    reply: str
    emotion: str
    concern_level: str = "none"
    suggest_call: bool = False
    guardian_phone: str | None = None


@router.post("", response_model=CheckinCreated, dependencies=[DemoKey])
async def create(body: CheckinIn, engine: EngineDep, settings: SettingsDep) -> CheckinCreated:
    row = await mood.record(engine, DEMO_CHILD_ID, body.mood, body.source, body.context)
    return CheckinCreated.model_validate(
        {
            **row,
            "reply": mood.MOOD_REPLIES[body.mood],
            "emotion": mood.MOOD_EMOTIONS[body.mood],
            **concern_fields(from_mood(body.mood), settings),
        }
    )


@router.get("", response_model=list[CheckinOut])
async def list_checkins(engine: EngineDep, days: int = Query(7, ge=1, le=90)) -> list[CheckinOut]:
    return [CheckinOut.model_validate(r) for r in await mood.recent(engine, DEMO_CHILD_ID, days)]
