"""SMS delivery through Twilio's REST API (a trial account works for verified numbers).

Runs as an ARQ job so a slow Twilio call never delays rule evaluation. Without Twilio
credentials the notification is marked `dry_run` and logged, so local dev and tests
never send real texts.
"""

from __future__ import annotations

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.log import get_logger
from sugarscout.settings import Settings

log = get_logger(__name__)

TWILIO_API = "https://api.twilio.com/2010-04-01"


async def deliver(engine: AsyncEngine, settings: Settings, notification_id: int) -> str:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT body, status FROM notifications WHERE id = :id AND channel = 'sms'"),
                {"id": notification_id},
            )
        ).first()
    if row is None or row.status != "queued":
        return "noop"

    status, sid, error = "dry_run", None, None
    if settings.twilio_configured:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{TWILIO_API}/Accounts/{settings.twilio_account_sid}/Messages.json",
                    auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                    data={
                        "To": settings.parent_phone,
                        "From": settings.twilio_from,
                        # Trial accounts can't send custom text; the dashboard still
                        # shows SugarScout's own wording from notifications.body.
                        "Body": settings.twilio_trial_template or row.body,
                    },
                )
            if resp.status_code in (200, 201):
                status, sid = "sent", resp.json().get("sid")
            else:
                status = "failed"
                error = f"twilio {resp.status_code}: {resp.json().get('message', resp.text)[:300]}"
        except httpx.HTTPError as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """UPDATE notifications
                   SET status = :s, provider_message_id = :sid, error = :e, sent_at = now()
                   WHERE id = :id"""
            ),
            {"s": status, "sid": sid, "e": error, "id": notification_id},
        )
    log.info(
        "sms.delivered",
        trial_template=settings.twilio_trial_template or None,
        notification_id=notification_id,
        status=status,
        error=error,
        body=row.body,
    )
    return status
