"""Browser push notifications to the parent's devices (Web Push with VAPID keys).

This is how the parent hears about the child in the child's own terms ("Alex's glucose
may reach about 52 in ~20 min. Alex said they feel shaky.") without carrier rules or
SMS templates. The worker's push outbox delivers every queued push notification.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pywebpush import WebPushException, webpush
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.log import get_logger
from sugarscout.settings import Settings

log = get_logger(__name__)

TTL_S = 60 * 30


def payload(title: str, body: str, *, tag: str, urgent: bool, url: str = "/parent") -> str:
    return json.dumps({"title": title, "body": body, "tag": tag, "urgent": urgent, "url": url})


def _send_one(settings: Settings, sub: dict[str, Any], data: str, urgent: bool) -> int:
    """Returns the push service's HTTP status (201 on success)."""
    try:
        resp = webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
            data=data,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=TTL_S,
            headers={"Urgency": "high" if urgent else "normal"},
            timeout=10,
        )
        return int(getattr(resp, "status_code", 201))
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", 0) if exc.response is not None else 0
        log.warning("push.failed", status=status, error=str(exc)[:200])
        return int(status or 0)


async def send_to_all(
    engine: AsyncEngine, settings: Settings, data: str, urgent: bool
) -> tuple[int, int]:
    """Send one payload to every subscribed device. Returns (delivered, devices).
    Subscriptions the push service says are gone (404/410) are removed."""
    async with engine.connect() as conn:
        subs = [
            dict(r._mapping)
            for r in (
                await conn.execute(text("SELECT id, endpoint, keys FROM push_subscriptions"))
            ).all()
        ]
    if not subs:
        return 0, 0
    statuses = await asyncio.gather(
        *(asyncio.to_thread(_send_one, settings, s, data, urgent) for s in subs)
    )
    gone = [s["id"] for s, st in zip(subs, statuses, strict=True) if st in (404, 410)]
    if gone:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM push_subscriptions WHERE id = ANY(:ids)"), {"ids": gone}
            )
    return sum(1 for st in statuses if 200 <= st < 300), len(subs)


async def deliver_pending(
    engine: AsyncEngine, settings: Settings, child_name: str, limit: int = 25
) -> int:
    """Deliver queued push notifications. Returns how many were processed."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT n.id, n.kind, n.body, a.id AS alert_id, a.rule_type, a.severity
                       FROM notifications n JOIN alerts a ON a.id = n.alert_id
                       WHERE n.channel = 'push' AND n.status = 'queued'
                       ORDER BY n.id LIMIT :n"""
                ),
                {"n": limit},
            )
        ).all()
    if not rows:
        return 0

    from sugarscout.alerts.service import RULE_LABELS  # local import: avoids a cycle

    for row in rows:
        label = RULE_LABELS.get(row.rule_type, row.rule_type)
        urgent = row.kind == "opened" and row.severity == "urgent"
        if row.kind == "resolved":
            title = f"{child_name}: {label} cleared"
        elif row.rule_type == "agent_heads_up":
            title = f"Scout heads-up about {child_name}"
        else:
            title = f"{'Urgent: ' if urgent else ''}{child_name} · {label}"

        status, error = "dry_run", None
        if settings.push_configured:
            delivered, devices = await send_to_all(
                engine,
                settings,
                payload(title, row.body, tag=f"alert-{row.alert_id}", urgent=urgent),
                urgent,
            )
            if devices == 0:
                status, error = "skipped", "no devices subscribed"
            elif delivered == 0:
                status, error = "failed", "no device accepted the push"
            else:
                status = "sent"
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """UPDATE notifications SET status = :s, error = :e, sent_at = now()
                       WHERE id = :id"""
                ),
                {"s": status, "e": error, "id": row.id},
            )
        log.info("push.delivered", notification_id=row.id, status=status, title=title)
    return len(rows)
