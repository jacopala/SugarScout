"""Hackathon demo family: one child, a fixed id, and a placeholder care plan.

In the full design the care plan is parent-configured (Section 6.1); here it's a fixed
set of calm, plan-relay reminders the companion shows while an alert is open. None of
them give dosing advice. They only relay "what your plan says to do".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.dev.seed import child_ids, seed
from sugarscout.log import get_logger
from sugarscout.settings import Settings

log = get_logger(__name__)

DEMO_CHILD_ID: uuid.UUID = child_ids(1)[0]

# Child-facing reminders, keyed by rule type. Calm and actionable (Section 10.1).
CHILD_REMINDERS: dict[str, str] = {
    "urgent_low": "Time to treat a low, just like your plan says. Have your fast sugar snack "
    "now and tell a grown-up nearby.",
    "low": "Your number is getting low. Let's follow your plan: have your fast sugar snack "
    "and tell a grown-up.",
    "rapid_drop": "Your number is dropping quickly. Please find a grown-up and check in together.",
    "high": "Your number is running high. Please let a grown-up know so you can check your "
    "plan together.",
    "data_gap": "I can't see your sensor right now. Can you ask a grown-up to take a look?",
    "symptoms_reported": "Thanks for telling me how you feel. I've let your grown-up know. "
    "Please sit down and follow your plan.",
    "predicted_urgent_low": "Your number is heading low. Please find a grown-up now and "
    "follow your plan.",
    "predicted_low": "Your number is going down. Let's check in with a grown-up soon.",
    "help_request": "I told your grown-up you need help. Stay where you are; they're coming.",
    "emergency_language": "I've let your grown-up know. Stay where you are, and if someone "
    "is nearby, tell them how you feel right now.",
}

# Reminder priority when several alerts are open at once.
REMINDER_PRIORITY = [
    "help_request",
    "emergency_language",
    "symptoms_reported",
    "urgent_low",
    "predicted_urgent_low",
    "low",
    "rapid_drop",
    "predicted_low",
    "data_gap",
    "high",
]


async def ensure_demo_child(engine: AsyncEngine, settings: Settings) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO children (id, first_name, age_band) VALUES (:id, :name, :age)
                   ON CONFLICT (id) DO UPDATE
                   SET first_name = EXCLUDED.first_name, age_band = EXCLUDED.age_band"""
            ),
            {
                "id": DEMO_CHILD_ID,
                "name": settings.demo_child_name,
                "age": settings.demo_child_age_band,
            },
        )


async def ensure_history(engine: AsyncEngine, settings: Settings) -> int:
    """Backfill `sim_history_days` of 5-minute readings ending an hour ago, once.

    Ending an hour back keeps the backfill out of the live 10-minute chart and out of
    the rules window, so it never interleaves with the simulator's 5-second stream.
    """
    async with engine.connect() as conn:
        has_history = (
            await conn.execute(
                text(
                    """SELECT EXISTS (SELECT 1 FROM glucose_readings
                       WHERE child_id = :c AND ts < now() - INTERVAL '1 day')"""
                ),
                {"c": DEMO_CHILD_ID},
            )
        ).scalar_one()
    if has_history:
        return 0
    inserted = await seed(
        engine,
        1,
        settings.sim_history_days,
        refresh=True,
        until=datetime.now(UTC) - timedelta(hours=1),
        ids=[DEMO_CHILD_ID],
    )
    log.info("demo.history_backfilled", rows=inserted, days=settings.sim_history_days)
    return inserted
