"""Presenter controls for the fake CGM, plus the child-facing status."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from sugarscout.api.deps import DemoKey, EngineDep, RedisDep, SettingsDep, enqueue
from sugarscout.demo import CHILD_REMINDERS, DEMO_CHILD_ID, REMINDER_PRIORITY
from sugarscout.sim.cgm import SCENARIO_LABELS, Scenario, add_effect, load_state, set_scenario

router = APIRouter(tags=["demo"])


class ScenarioOption(BaseModel):
    id: Scenario
    label: str


class DemoState(BaseModel):
    child_name: str
    scenario: Scenario
    scenarios: list[ScenarioOption]
    sms_mode: str
    llm_enabled: bool
    access_code_required: bool


class ScenarioIn(BaseModel):
    scenario: Scenario


def _state(settings: SettingsDep, scenario: Scenario) -> DemoState:
    return DemoState(
        child_name=settings.demo_child_name,
        scenario=scenario,
        scenarios=[ScenarioOption(id=s, label=SCENARIO_LABELS[s]) for s in Scenario],
        sms_mode="live" if settings.twilio_configured else "dry_run",
        llm_enabled=settings.llm_configured,
        access_code_required=bool(settings.demo_access_code),
    )


@router.get("/demo/state", response_model=DemoState)
async def demo_state(settings: SettingsDep, redis: RedisDep) -> DemoState:
    return _state(settings, (await load_state(redis)).scenario)


@router.post("/demo/scenario", response_model=DemoState, dependencies=[DemoKey])
async def choose_scenario(body: ScenarioIn, settings: SettingsDep, redis: RedisDep) -> DemoState:
    state = await set_scenario(redis, body.scenario)
    return _state(settings, state.scenario)


class DemoEventIn(BaseModel):
    kind: Literal["snack_no_insulin", "exercise"]


@router.post("/demo/event", dependencies=[DemoKey])
async def demo_event(
    body: DemoEventIn, request: Request, engine: EngineDep, redis: RedisDep
) -> dict[str, str]:
    """Presenter shortcuts for the demo story. "Big snack, no insulin" logs a snack as if the
    child tapped it (with a fixed estimate so the demo is repeatable); "Exercise drop"
    nudges the fake CGM down."""
    if body.kind == "exercise":
        await add_effect(redis, "exercise")
        return {"ok": "exercise"}
    analysis = {
        "items": [
            {"name": "juice box", "carbs_g": 24, "sugar_g": 22, "contains_gluten": False},
            {
                "name": "chocolate chip cookies",
                "carbs_g": 30,
                "sugar_g": 16,
                "contains_gluten": True,
            },
        ],
        "confidence": "medium",
        "note": "Most of the sugar is from the juice.",
        "total_carbs_g": 54,
        "total_sugar_g": 38,
        "contains_gluten": True,
    }
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO meals (child_id, description, source, analysis_status, analysis,
                                      model, analyzed_at)
                   VALUES (:c, 'juice box and two cookies', 'tap', 'ok', CAST(:a AS jsonb),
                           'demo preset', now())"""
            ),
            {"c": DEMO_CHILD_ID, "a": json.dumps(analysis)},
        )
    await add_effect(redis, "meal", 54)
    await enqueue(request, "agent_tick")
    return {"ok": "snack_no_insulin"}


@router.post("/demo/check-key", dependencies=[DemoKey])
async def check_key() -> dict[str, bool]:
    return {"ok": True}


class ChildStatus(BaseModel):
    first_name: str
    reminder: str | None
    reminder_rule: str | None


@router.get("/child/status", response_model=ChildStatus)
async def child_status(engine: EngineDep, settings: SettingsDep) -> ChildStatus:
    """What the child view shows: a calm care-plan reminder while an alert is active.
    Deliberately no glucose numbers (Section 10.1)."""
    async with engine.connect() as conn:
        active = set(
            (
                await conn.execute(
                    text(
                        """SELECT rule_type FROM alerts
                           WHERE child_id = :c AND state <> 'resolved'"""
                    ),
                    {"c": DEMO_CHILD_ID},
                )
            )
            .scalars()
            .all()
        )
    rule = next((r for r in REMINDER_PRIORITY if r in active), None)
    return ChildStatus(
        first_name=settings.demo_child_name,
        reminder=CHILD_REMINDERS.get(rule) if rule else None,
        reminder_rule=rule,
    )
