"""Mood check-ins (1-5). Shared labels so the API, chat context, and summary agree."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

MOOD_LABELS: dict[int, str] = {
    1: "sad",
    2: "disappointed",
    3: "normal",
    4: "peaceful",
    5: "happy",
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
    1: "I'm sorry you're feeling sad. I'm here with you. Want to tell me about it? "
    "You can always tell a grown-up too.",
    2: "Aw, feeling disappointed is hard. Want to tell me what happened?",
    3: "Thanks for telling me! A normal day is a good day. Want to chat for a bit?",
    4: "Feeling peaceful sounds so nice. What's been calm and cozy today?",
    5: "Yay! I'm so happy you're happy! What made today awesome?",
}


# How Scout's voice sounds for each mood reply.
MOOD_EMOTIONS: dict[int, str] = {1: "sad", 2: "sad", 3: "neutral", 4: "happy", 5: "happy"}
