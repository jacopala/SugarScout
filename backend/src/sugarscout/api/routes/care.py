"""Child safety and care actions: the Help button, and meal logging."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from sugarscout.ai.meals import CHILD_MEAL_REPLY, recent_meals, record_meal
from sugarscout.alerts.service import raise_alert
from sugarscout.api.deps import DemoKey, EngineDep, RedisDep, SettingsDep, enqueue
from sugarscout.demo import CHILD_REMINDERS, DEMO_CHILD_ID
from sugarscout.rules.engine import URGENT, RuleHit

router = APIRouter(tags=["care"])


class HelpOut(BaseModel):
    sent: bool
    already_open: bool
    reply: str


@router.post("/help", response_model=HelpOut, dependencies=[DemoKey])
async def help_request(
    request: Request, engine: EngineDep, redis: RedisDep, settings: SettingsDep
) -> HelpOut:
    """The child pressed Help and confirmed. Deterministic: no model involved."""
    name = settings.demo_child_name
    hit = RuleHit(
        "help_request",
        URGENT,
        f"{name} pressed the Help button and asked for a grown-up.",
        {"source": "help_button", "at": datetime.now(UTC).isoformat()},
    )
    async with engine.begin() as conn:
        alert_id, sms_ids = await raise_alert(conn, redis, settings, DEMO_CHILD_ID, name, hit)
    for nid in sms_ids:
        await enqueue(request, "send_sms", nid)
    return HelpOut(sent=True, already_open=alert_id is None, reply=CHILD_REMINDERS["help_request"])


class MealIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    source: Literal["voice", "tap", "text"] = "text"


class MealCreated(BaseModel):
    id: int
    reply: str


class MealOut(BaseModel):
    id: int
    description: str
    source: str
    analysis_status: str
    analysis: dict[str, Any] | None
    created_at: datetime
    glucose_1h: int | None


@router.post("/meals", response_model=MealCreated, dependencies=[DemoKey])
async def log_meal(body: MealIn, request: Request, engine: EngineDep) -> MealCreated:
    meal_id = await record_meal(engine, DEMO_CHILD_ID, body.description, body.source)
    # The estimate runs in the worker so the child gets an instant, friendly reply.
    await enqueue(request, "analyze_meal", meal_id)
    return MealCreated(id=meal_id, reply=CHILD_MEAL_REPLY)


@router.get("/meals", response_model=list[MealOut])
async def list_meals(engine: EngineDep, days: int = Query(1, ge=1, le=30)) -> list[MealOut]:
    return [MealOut.model_validate(m) for m in await recent_meals(engine, DEMO_CHILD_ID, days)]
