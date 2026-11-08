"""Presenter controls for the fake CGM, plus the child-facing status."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from sugarscout.api.deps import DemoKey, EngineDep, RedisDep, SettingsDep
from sugarscout.demo import CHILD_REMINDERS, DEMO_CHILD_ID, REMINDER_PRIORITY
from sugarscout.sim.cgm import SCENARIO_LABELS, Scenario, load_state, set_scenario

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
