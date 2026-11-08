"""Fake CGM for the demo.

Writes one reading per tick with a real timestamp, so every `now()`-based query works
unchanged; the glucose *dynamics* are sped up so a "rapid drop" plays out in ~30 s.
The presenter switches scenarios from the dashboard. State lives in Redis.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from redis.asyncio import Redis

STATE_KEY = "sim:state"


class Scenario(StrEnum):
    STEADY = "steady"
    DRIFT_LOW = "drift_low"
    RAPID_DROP = "rapid_drop"
    HIGH = "high"
    RECOVER = "recover"
    DROPOUT = "dropout"


@dataclass(frozen=True)
class Dynamics:
    target: float
    rate: float  # fraction of the gap to the target closed per tick
    noise: float  # +/- uniform noise per tick, mg/dL


DYNAMICS: dict[Scenario, Dynamics] = {
    Scenario.STEADY: Dynamics(target=120, rate=0.10, noise=2.5),
    Scenario.DRIFT_LOW: Dynamics(target=62, rate=0.06, noise=1.5),
    Scenario.RAPID_DROP: Dynamics(target=45, rate=0.30, noise=1.5),
    Scenario.HIGH: Dynamics(target=290, rate=0.15, noise=2.5),
    Scenario.RECOVER: Dynamics(target=120, rate=0.25, noise=1.5),
}

SCENARIO_LABELS: dict[Scenario, str] = {
    Scenario.STEADY: "Steady",
    Scenario.DRIFT_LOW: "Slow drift low",
    Scenario.RAPID_DROP: "Rapid drop",
    Scenario.HIGH: "Going high",
    Scenario.RECOVER: "Recover",
    Scenario.DROPOUT: "Sensor dropout",
}

MIN_VALUE, MAX_VALUE = 40, 400


@dataclass
class SimState:
    scenario: Scenario = Scenario.STEADY
    value: float = 120.0
    recent: list[int] = field(default_factory=list)  # last few written values, oldest first
    # Demo-only meal/insulin/exercise effects: an offset added to the scenario's target,
    # changed a little each tick by the active effects. Not a physiological model.
    offset: float = 0.0
    effects: list[dict[str, float]] = field(default_factory=list)  # {per_tick, remaining}

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes | None) -> SimState:
        if not raw:
            return cls()
        data = json.loads(raw)
        return cls(
            scenario=Scenario(data.get("scenario", Scenario.STEADY)),
            value=float(data.get("value", 120.0)),
            recent=[int(v) for v in data.get("recent", [])],
            offset=float(data.get("offset", 0.0)),
            effects=[
                {"per_tick": float(e["per_tick"]), "remaining": float(e["remaining"])}
                for e in data.get("effects", [])
            ],
        )


def step(state: SimState, rng: random.Random) -> int | None:
    """Advance one tick. Returns the reading to write, or None during a dropout."""
    if state.scenario is Scenario.DROPOUT:
        return None
    dyn = DYNAMICS[state.scenario]
    advance_effects(state)
    target = max(MIN_VALUE, min(MAX_VALUE, dyn.target + state.offset))
    # Effects need a firmer pull than "steady" so a meal rise actually shows up.
    rate = max(dyn.rate, 0.2) if state.effects else dyn.rate
    nxt = state.value + (target - state.value) * rate + rng.uniform(-dyn.noise, dyn.noise)
    nxt = max(MIN_VALUE, min(MAX_VALUE, nxt))
    state.value = nxt
    reading = round(nxt)
    state.recent = [*state.recent, reading][-4:]
    # A recovery settles back into steady once it is close to the target.
    if state.scenario is Scenario.RECOVER and abs(nxt - target) < 5:
        state.scenario = Scenario.STEADY
    return reading


def trend_label(values: list[int]) -> str:
    """CGM-style trend arrow from the average change per tick over recent values."""
    if len(values) < 2:
        return "flat"
    per_tick = (values[-1] - values[0]) / (len(values) - 1)
    if per_tick <= -6:
        return "double_down"
    if per_tick <= -2:
        return "down"
    if per_tick >= 6:
        return "double_up"
    if per_tick >= 2:
        return "up"
    return "flat"


async def load_state(redis: Redis) -> SimState:
    return SimState.from_json(await redis.get(STATE_KEY))


async def save_state(redis: Redis, state: SimState) -> None:
    await redis.set(STATE_KEY, state.to_json())


async def set_scenario(redis: Redis, scenario: Scenario) -> SimState:
    state = await load_state(redis)
    state.scenario = scenario
    if scenario in (Scenario.RECOVER, Scenario.STEADY):
        await add_effect(redis, "reset")
    await save_state(redis, state)
    return state


# ---- Demo effects: meals, insulin, exercise ---------------------------------------------
# A deliberately simple toy so the demo reacts to what the child eats and what the parent
# logs. It is NOT a model of insulin action and is never used for anything but the fake CGM.

EFFECTS_KEY = "sim:effects"
EFFECT_TICKS = 12
MEAL_MG_PER_G_CARB = 3.0
MAX_OFFSET, MIN_OFFSET = 200.0, -90.0


def advance_effects(state: SimState) -> None:
    for e in state.effects:
        state.offset += e["per_tick"]
        e["remaining"] -= 1
    state.effects = [e for e in state.effects if e["remaining"] > 0]
    state.offset = max(MIN_OFFSET, min(MAX_OFFSET, state.offset * 0.995))


def apply_effect(state: SimState, kind: str, carbs_g: float = 0.0) -> None:
    if kind == "meal":
        rise = min(carbs_g * MEAL_MG_PER_G_CARB, MAX_OFFSET)
        state.effects.append({"per_tick": rise / EFFECT_TICKS, "remaining": EFFECT_TICKS})
    elif kind == "insulin":
        # Cancel most of any rise still to come, and bring the current rise back down.
        for e in state.effects:
            if e["per_tick"] > 0:
                e["per_tick"] /= 3
        drop = max(state.offset, 0.0) * 0.85 + 10
        state.effects.append({"per_tick": -drop / EFFECT_TICKS, "remaining": EFFECT_TICKS})
    elif kind == "exercise":
        state.effects.append({"per_tick": -70.0 / EFFECT_TICKS, "remaining": EFFECT_TICKS})
    elif kind == "reset":
        state.effects = []
        state.offset = 0.0


async def add_effect(redis: Redis, kind: str, carbs_g: float = 0.0) -> None:
    """Queue an effect; the next simulator tick applies it (no race with the worker)."""
    await redis.rpush(EFFECTS_KEY, json.dumps({"kind": kind, "carbs_g": carbs_g}))  # type: ignore[misc]


async def drain_effects(redis: Redis, state: SimState) -> list[str]:
    applied: list[str] = []
    while True:
        raw = await redis.lpop(EFFECTS_KEY)  # type: ignore[misc]
        if raw is None:
            return applied
        e = json.loads(raw)
        apply_effect(state, e["kind"], float(e.get("carbs_g", 0)))
        applied.append(e["kind"])
