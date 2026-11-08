"""Alert lifecycle: open, dedupe, acknowledge, auto-resolve, and fan out notifications.

- One active alert per rule per child (partial unique index), so a condition that
  persists across ticks is one episode, not a stream of messages (Section 6.3).
- An alert resolves automatically when its rule is evaluated and no longer holds, and
  the parent is told it cleared.
- SMS goes out for urgent and fail-loudly rules on open, with a per-rule cooldown, and
  on resolve only if an SMS went out when it opened.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sugarscout.rules.engine import Evaluation, RuleHit
from sugarscout.settings import Settings

SMS_ON_OPEN = frozenset(
    {
        "urgent_low",
        "predicted_urgent_low",
        "data_gap",
        "emergency_language",
        "help_request",
        "symptoms_reported",
    }
)
# Rules that describe the same danger share one SMS cooldown, so "urgent low soon"
# followed by "urgent low" doesn't text the parent twice in a minute.
SMS_FAMILY: dict[str, str] = {"predicted_urgent_low": "low", "urgent_low": "low"}

RULE_LABELS: dict[str, str] = {
    "urgent_low": "urgent low",
    "low": "low glucose",
    "high": "high glucose",
    "rapid_drop": "rapid drop",
    "rapid_rise": "rapid rise",
    "data_gap": "sensor data gap",
    "emergency_language": "companion safety",
    "help_request": "help request",
    "predicted_low": "low soon",
    "predicted_urgent_low": "urgent low soon",
    "predicted_high": "high soon",
    "symptoms_reported": "symptoms reported",
    "agent_heads_up": "Scout heads-up",
    "child_concern": "worried words",
}


def sms_body(rule_type: str, kind: str, name: str) -> str:
    """Minimal SMS text: no readings or other health detail (Section 6.3)."""
    if kind == "resolved":
        return f"SugarScout: {name}'s {RULE_LABELS.get(rule_type, rule_type)} alert has cleared."
    if rule_type == "urgent_low":
        return f"SugarScout: {name}'s glucose is urgently low. Please check on {name} now."
    if rule_type == "data_gap":
        return (
            f"SugarScout: {name}'s glucose sensor stopped sending data. Please check the dashboard."
        )
    if rule_type == "help_request":
        return (
            f"SugarScout: {name} pressed the Help button and needs you. Please check on {name} now."
        )
    if rule_type == "emergency_language":
        return (
            f"SugarScout: {name} said something in the companion app that needs your "
            f"attention. Please check on {name} now."
        )
    return f"SugarScout: {name} has a {RULE_LABELS.get(rule_type, rule_type)} alert. Please check the dashboard."


@dataclass(frozen=True)
class AlertEvent:
    alert_id: int
    rule_type: str
    kind: str  # opened | resolved


async def _insert_alert(conn: AsyncConnection, child_id: uuid.UUID, hit: RuleHit) -> int | None:
    row = (
        await conn.execute(
            text(
                """INSERT INTO alerts (child_id, rule_type, severity, message, trigger_data)
                   VALUES (:c, :r, :s, :m, CAST(:t AS jsonb))
                   ON CONFLICT (child_id, rule_type) WHERE state <> 'resolved' DO NOTHING
                   RETURNING id"""
            ),
            {
                "c": child_id,
                "r": hit.rule_type,
                "s": hit.severity,
                "m": hit.message,
                "t": json.dumps(hit.trigger_data, default=str),
            },
        )
    ).first()
    return int(row.id) if row else None


async def _notify(
    conn: AsyncConnection,
    redis: Redis,
    settings: Settings,
    child_id: uuid.UUID,
    child_name: str,
    event: AlertEvent,
    dashboard_body: str,
) -> int | None:
    """Write the dashboard notification, queue a browser push with the real message
    (delivered by the worker's push outbox), and, if warranted, a queued SMS. Returns
    the SMS notification id to deliver, if any."""
    await conn.execute(
        text(
            """INSERT INTO notifications (alert_id, channel, kind, body, status, sent_at)
               VALUES (:a, 'dashboard', :k, :b, 'sent', now())"""
        ),
        {"a": event.alert_id, "k": event.kind, "b": dashboard_body},
    )
    await conn.execute(
        text(
            """INSERT INTO notifications (alert_id, channel, kind, recipient, body, status)
               VALUES (:a, 'push', :k, 'parent devices', :b, 'queued')"""
        ),
        {"a": event.alert_id, "k": event.kind, "b": dashboard_body},
    )

    if event.kind == "opened":
        if event.rule_type not in SMS_ON_OPEN:
            return None
        family = SMS_FAMILY.get(event.rule_type, event.rule_type)
        cooldown_key = f"sms:cooldown:{child_id}:{family}"
        fresh = await redis.set(cooldown_key, "1", nx=True, ex=settings.sms_cooldown_seconds)
        status, error = ("queued", None) if fresh else ("skipped", "cooldown")
    else:
        sent_on_open = (
            await conn.execute(
                text(
                    """SELECT EXISTS (SELECT 1 FROM notifications
                       WHERE alert_id = :a AND channel = 'sms' AND kind = 'opened'
                         AND status IN ('queued', 'sent', 'dry_run'))"""
                ),
                {"a": event.alert_id},
            )
        ).scalar_one()
        if not sent_on_open:
            return None
        status, error = "queued", None

    row = (
        await conn.execute(
            text(
                """INSERT INTO notifications (alert_id, channel, kind, recipient, body, status, error)
                   VALUES (:a, 'sms', :k, :to, :b, :s, :e) RETURNING id"""
            ),
            {
                "a": event.alert_id,
                "k": event.kind,
                "to": settings.parent_phone or None,
                "b": sms_body(event.rule_type, event.kind, child_name),
                "s": status,
                "e": error,
            },
        )
    ).one()
    return int(row.id) if status == "queued" else None


async def sync_alerts(
    conn: AsyncConnection,
    redis: Redis,
    settings: Settings,
    child_id: uuid.UUID,
    child_name: str,
    evaluation: Evaluation,
) -> tuple[list[AlertEvent], list[int]]:
    """Reconcile active alerts with the latest evaluation. Returns the lifecycle events
    and the SMS notification ids to deliver."""
    events: list[AlertEvent] = []
    sms_ids: list[int] = []

    for hit in evaluation.hits:
        alert_id = await _insert_alert(conn, child_id, hit)
        if alert_id is None:
            continue  # same episode already active
        ev = AlertEvent(alert_id, hit.rule_type, "opened")
        events.append(ev)
        if (
            sid := await _notify(conn, redis, settings, child_id, child_name, ev, hit.message)
        ) is not None:
            sms_ids.append(sid)

    cleared = sorted(evaluation.evaluated - evaluation.hit_types)
    if cleared:
        rows = (
            await conn.execute(
                text(
                    # Cleared alerts become unread again so the parent sees the good news.
                    """UPDATE alerts SET state = 'resolved', resolved_at = now(), read_at = NULL
                       WHERE child_id = :c AND state <> 'resolved' AND rule_type = ANY(:rules)
                       RETURNING id, rule_type"""
                ),
                {"c": child_id, "rules": cleared},
            )
        ).all()
        for row in rows:
            ev = AlertEvent(int(row.id), row.rule_type, "resolved")
            events.append(ev)
            body = f"{child_name}'s {RULE_LABELS.get(row.rule_type, row.rule_type)} alert cleared."
            if (
                sid := await _notify(conn, redis, settings, child_id, child_name, ev, body)
            ) is not None:
                sms_ids.append(sid)

    return events, sms_ids


async def raise_alert(
    conn: AsyncConnection,
    redis: Redis,
    settings: Settings,
    child_id: uuid.UUID,
    child_name: str,
    hit: RuleHit,
) -> tuple[int | None, list[int]]:
    """Open a non-reading alert (e.g. emergency language from chat)."""
    alert_id = await _insert_alert(conn, child_id, hit)
    if alert_id is None:
        return None, []
    ev = AlertEvent(alert_id, hit.rule_type, "opened")
    sid = await _notify(conn, redis, settings, child_id, child_name, ev, hit.message)
    return alert_id, [sid] if sid is not None else []


# Alerts no reading can clear: a parent acknowledgement closes them.
ACK_RESOLVES = frozenset(
    {"emergency_language", "help_request", "symptoms_reported", "agent_heads_up", "child_concern"}
)


async def acknowledge(conn: AsyncConnection, alert_id: int) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            text(
                """UPDATE alerts
                   SET acknowledged_at = COALESCE(acknowledged_at, now()),
                       state = CASE WHEN rule_type = ANY(:ack_resolves) THEN 'resolved'
                                    WHEN state = 'open' THEN 'acknowledged' ELSE state END,
                       resolved_at = CASE WHEN rule_type = ANY(:ack_resolves)
                                          THEN COALESCE(resolved_at, now()) ELSE resolved_at END
                   WHERE id = :id
                   RETURNING id, rule_type, state, acknowledged_at, resolved_at"""
            ),
            {"id": alert_id, "ack_resolves": sorted(ACK_RESOLVES)},
        )
    ).first()
    return dict(row._mapping) if row else None
