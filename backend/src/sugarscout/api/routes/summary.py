"""AI parent summary: latest, and generate-now."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from sugarscout.ai.summary import generate_summary
from sugarscout.api.deps import DemoKey, EngineDep, SettingsDep
from sugarscout.demo import DEMO_CHILD_ID

router = APIRouter(prefix="/summary", tags=["summary"])


class SummaryOut(BaseModel):
    id: int
    created_at: datetime
    model: str | None
    status: str
    error: str | None
    stats: dict[str, Any]
    content: dict[str, Any] | None


@router.get("", response_model=SummaryOut | None)
async def latest(engine: EngineDep) -> SummaryOut | None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """SELECT id, created_at, model, status, error, stats, content FROM summaries
                       WHERE child_id = :c ORDER BY created_at DESC LIMIT 1"""
                ),
                {"c": DEMO_CHILD_ID},
            )
        ).first()
    return SummaryOut.model_validate(row._mapping) if row else None


@router.post("", response_model=SummaryOut, dependencies=[DemoKey])
async def generate(request: Request, engine: EngineDep, settings: SettingsDep) -> SummaryOut:
    result = await generate_summary(
        engine, settings, request.app.state.llm, DEMO_CHILD_ID, settings.demo_child_name
    )
    return SummaryOut.model_validate(result)
