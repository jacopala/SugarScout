"""Meal logging and AI intake estimates.

The child says or taps what they ate. Nemotron estimates sugar (grams) and whether each
item likely contains gluten, for the PARENT only. The child never sees numbers or
judgement about food. Estimates are clearly labelled and are never a carb count for
dosing (Section 2.2): outputs are validated and anything that reads like treatment
advice is rejected.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.ai.gateway import ChatModel
from sugarscout.ai.safety import check_output
from sugarscout.ai.summary import _PARENT_ADVICE, SummaryRejected, _extract_json
from sugarscout.log import get_logger
from sugarscout.settings import Settings

log = get_logger(__name__)

# What Scout says to the child after a meal is logged: warm, no numbers, no judgement.
CHILD_MEAL_REPLY = "Yum! Thanks for telling me. I'll share it with your grown-up."

MAX_SUGAR_G = 250.0
MAX_CARBS_G = 300.0


class MealItem(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    carbs_g: float = Field(ge=0, le=MAX_CARBS_G)
    sugar_g: float = Field(ge=0, le=MAX_SUGAR_G)
    contains_gluten: bool


class MealAnalysis(BaseModel):
    items: list[MealItem] = Field(min_length=1, max_length=12)
    confidence: str = Field(pattern="^(high|medium|low)$")
    note: str = Field(default="", max_length=240)

    @property
    def total_sugar_g(self) -> float:
        return round(sum(i.sugar_g for i in self.items), 1)

    @property
    def total_carbs_g(self) -> float:
        return round(sum(i.carbs_g for i in self.items), 1)

    @property
    def contains_gluten(self) -> bool:
        return any(i.contains_gluten for i in self.items)


SYSTEM_PROMPT = """You estimate what a child ate, for their parent's records.

Given the child's own words, list each food or drink with:
- name: short, plain name
- carbs_g: estimated TOTAL carbohydrates in grams for a typical child portion (a number)
- sugar_g: estimated total sugars in grams (part of the carbs; never more than carbs_g)
- contains_gluten: true if it usually contains wheat, barley, or rye

Use typical kids' portions. If the description is vague, pick the most common version
and set confidence to "low". Never give insulin, dosing, carb-ratio, or treatment advice.
The optional "note" is one short, neutral sentence for the parent (e.g. which item is
the main sugar source); leave it empty if there is nothing useful.

Return ONLY JSON:
{"items":[{"name":"apple juice","carbs_g":24,"sugar_g":22,"contains_gluten":false}],
 "confidence":"medium","note":""}"""


def validate_analysis(raw: str) -> MealAnalysis:
    try:
        analysis = MealAnalysis.model_validate(_extract_json(raw))
    except ValidationError as exc:
        raise SummaryRejected(f"schema: {exc.errors()[0]['msg']}") from exc
    for item in analysis.items:
        if item.sugar_g > item.carbs_g + 1:
            raise SummaryRejected(f"sugar exceeds carbs for {item.name}")
    for t in [analysis.note, *(i.name for i in analysis.items)]:
        if t and (check_output(t) or any(p.search(t.lower()) for p in _PARENT_ADVICE)):
            raise SummaryRejected(f"treatment advice: {t[:80]}")
    return analysis


async def record_meal(
    engine: AsyncEngine, child_id: uuid.UUID, description: str, source: str
) -> int:
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """INSERT INTO meals (child_id, description, source)
                       VALUES (:c, :d, :s) RETURNING id"""
                ),
                {"c": child_id, "d": description.strip(), "s": source},
            )
        ).one()
    return int(row.id)


async def analyze_meal(
    engine: AsyncEngine, settings: Settings, model: ChatModel | None, meal_id: int
) -> str:
    async with engine.connect() as conn:
        meal = (
            await conn.execute(
                text("SELECT description, analysis_status FROM meals WHERE id = :id"),
                {"id": meal_id},
            )
        ).first()
    if meal is None or meal.analysis_status != "pending":
        return "noop"

    status, analysis, error = "disabled", None, None
    if model is not None:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"The child said they ate: {meal.description}"},
        ]
        try:
            try:
                raw = await model.complete(
                    settings.nemotron_chat_model,
                    messages,
                    max_tokens=600,
                    temperature=0.1,
                    json_mode=True,
                )
            except Exception as exc:
                log.info("meal.json_mode_unsupported", error=repr(exc))
                raw = await model.complete(
                    settings.nemotron_chat_model, messages, max_tokens=600, temperature=0.1
                )
            parsed = validate_analysis(raw)
            analysis = {
                **parsed.model_dump(),
                "total_sugar_g": parsed.total_sugar_g,
                "total_carbs_g": parsed.total_carbs_g,
                "contains_gluten": parsed.contains_gluten,
            }
            status = "ok"
        except SummaryRejected as exc:
            status, error = "rejected", str(exc)
        except Exception as exc:
            status, error = "error", f"{type(exc).__name__}: {exc}"[:200]
    if error:
        log.warning("meal.analysis_failed", meal_id=meal_id, status=status, error=error)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """UPDATE meals SET analysis_status = :s, analysis = CAST(:a AS jsonb),
                          model = :m, analyzed_at = now()
                   WHERE id = :id"""
            ),
            {
                "s": status,
                "a": json.dumps(analysis) if analysis else None,
                "m": settings.nemotron_chat_model if model else None,
                "id": meal_id,
            },
        )
    return status


async def recent_meals(
    engine: AsyncEngine, child_id: uuid.UUID, days: int = 1
) -> list[dict[str, Any]]:
    """Meals with the glucose reading closest to one hour later (computed, not AI)."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT m.id, m.description, m.source, m.analysis_status, m.analysis,
                              m.created_at,
                              (SELECT g.value_mg_dl FROM glucose_readings g
                                WHERE g.child_id = m.child_id
                                  AND g.ts BETWEEN m.created_at + :lo AND m.created_at + :hi
                                ORDER BY abs(extract(epoch FROM g.ts - (m.created_at + :mid)))
                                LIMIT 1) AS glucose_1h
                       FROM meals m
                       WHERE m.child_id = :c AND m.created_at >= now() - make_interval(days => :d)
                       ORDER BY m.created_at DESC"""
                ),
                {
                    "c": child_id,
                    "d": days,
                    "lo": timedelta(minutes=45),
                    "hi": timedelta(minutes=75),
                    "mid": timedelta(minutes=60),
                },
            )
        ).all()
    return [dict(r._mapping) for r in rows]
