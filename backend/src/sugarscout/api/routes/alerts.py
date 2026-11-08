"""Alert history and acknowledgement for the parent dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from sugarscout.alerts.service import RULE_LABELS, acknowledge
from sugarscout.api.deps import DemoKey, EngineDep
from sugarscout.demo import DEMO_CHILD_ID

router = APIRouter(prefix="/alerts", tags=["alerts"])


class NotificationOut(BaseModel):
    id: int
    channel: str
    kind: str
    status: str
    body: str
    error: str | None
    created_at: datetime
    sent_at: datetime | None


class AlertOut(BaseModel):
    id: int
    rule_type: str
    label: str
    severity: str
    state: str
    message: str
    trigger_data: dict[str, Any]
    opened_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    read_at: datetime | None
    notifications: list[NotificationOut]


@router.get("", response_model=list[AlertOut])
async def list_alerts(engine: EngineDep, limit: int = Query(30, ge=1, le=200)) -> list[AlertOut]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT a.*, COALESCE(
                         (SELECT json_agg(n ORDER BY n.id) FROM notifications n WHERE n.alert_id = a.id),
                         '[]'::json) AS notifications
                       FROM alerts a WHERE a.child_id = :c AND a.dismissed_at IS NULL
                       ORDER BY (a.state <> 'resolved') DESC, a.opened_at DESC
                       LIMIT :limit"""
                ),
                {"c": DEMO_CHILD_ID, "limit": limit},
            )
        ).all()
    return [
        AlertOut(
            id=r.id,
            rule_type=r.rule_type,
            label=RULE_LABELS.get(r.rule_type, r.rule_type),
            severity=r.severity,
            state=r.state,
            message=r.message,
            trigger_data=r.trigger_data,
            opened_at=r.opened_at,
            acknowledged_at=r.acknowledged_at,
            resolved_at=r.resolved_at,
            read_at=r.read_at,
            notifications=[NotificationOut.model_validate(n) for n in r.notifications],
        )
        for r in rows
    ]


@router.post("/{alert_id}/ack", dependencies=[DemoKey])
async def ack(alert_id: int, engine: EngineDep) -> dict[str, Any]:
    async with engine.begin() as conn:
        row = await acknowledge(conn, alert_id)
    if row is None:
        raise HTTPException(404, "Alert not found")
    return row


class ReadIn(BaseModel):
    ids: list[int] = Field(max_length=200)


@router.post("/read", dependencies=[DemoKey])
async def mark_read(body: ReadIn, engine: EngineDep) -> dict[str, int]:
    """The parent opened the alerts pop-up: these alerts are now read."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """UPDATE alerts SET read_at = now()
                   WHERE child_id = :c AND id = ANY(:ids) AND read_at IS NULL"""
            ),
            {"c": DEMO_CHILD_ID, "ids": body.ids},
        )
    return {"marked": result.rowcount or 0}


@router.delete("/{alert_id}", dependencies=[DemoKey])
async def dismiss(alert_id: int, engine: EngineDep) -> dict[str, bool]:
    """Remove a read alert from the parent's list. It stays in the audit trail.
    An alert that is still open and unacknowledged can't be removed: it needs attention."""
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT state, read_at FROM alerts WHERE id = :id AND child_id = :c"),
                {"id": alert_id, "c": DEMO_CHILD_ID},
            )
        ).first()
        if row is None:
            raise HTTPException(404, "Alert not found")
        if row.read_at is None:
            raise HTTPException(409, "Read the alert before deleting it")
        if row.state == "open":
            raise HTTPException(409, "Acknowledge the alert before deleting it")
        await conn.execute(
            text("UPDATE alerts SET dismissed_at = now() WHERE id = :id"), {"id": alert_id}
        )
    return {"ok": True}
