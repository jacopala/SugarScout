"""Mood check-ins (1-5). Shared labels so the API, chat context, and summary agree."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

MOOD_LABELS: dict[int, str] = {
    1: "really bad",
    2: "not great",
    3: "okay",
    4: "good",
    5: "great",
}


async def record(
    engine: AsyncEngine, child_id: uuid.UUID, mood: int, source: str = "tap"
) -> dict[str, Any]:
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """INSERT INTO mood_checkins (child_id, mood, source) VALUES (:c, :m, :s)
                       RETURNING id, mood, source, created_at"""
                ),
                {"c": child_id, "m": mood, "s": source},
            )
        ).one()
    return {**row._mapping, "label": MOOD_LABELS[row.mood]}


async def recent(
    engine: AsyncEngine, child_id: uuid.UUID, days: int = 7, limit: int = 100
) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT id, mood, source, created_at FROM mood_checkins
                       WHERE child_id = :c AND created_at >= now() - make_interval(days => :d)
                       ORDER BY created_at DESC LIMIT :n"""
                ),
                {"c": child_id, "d": days, "n": limit},
            )
        ).all()
    return [{**r._mapping, "label": MOOD_LABELS[r.mood]} for r in rows]


async def latest_within(
    conn: AsyncConnection, child_id: uuid.UUID, hours: int
) -> tuple[int, datetime] | None:
    row = (
        await conn.execute(
            text(
                """SELECT mood, created_at FROM mood_checkins
                   WHERE child_id = :c AND created_at >= now() - make_interval(hours => :h)
                   ORDER BY created_at DESC LIMIT 1"""
            ),
            {"c": child_id, "h": hours},
        )
    ).first()
    return (int(row.mood), row.created_at) if row else None


# Scout's spoken reaction to each mood: fixed, gentle lines (no model involved).
MOOD_REPLIES: dict[int, str] = {
    1: "I'm sorry you're feeling really bad. I'm here with you. Want to tell me about it? "
    "You can always tell a grown-up too.",
    2: "I'm sorry you're feeling not great. Want to tell me about it?",
    3: "Thanks for telling me. Okay days are okay! Want to chat for a bit?",
    4: "Yay, I'm glad you're feeling good! What's been fun today?",
    5: "Woohoo! I'm so happy you feel great! What made today awesome?",
}
