"""Parent device registration for browser push."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from sugarscout.api.deps import DemoKey, EngineDep, SettingsDep
from sugarscout.notify.push import payload, send_to_all

router = APIRouter(prefix="/push", tags=["push"])


class PushConfig(BaseModel):
    enabled: bool
    public_key: str | None
    devices: int


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://")
    keys: SubscriptionKeys


@router.get("/config", response_model=PushConfig)
async def config(engine: EngineDep, settings: SettingsDep) -> PushConfig:
    async with engine.connect() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM push_subscriptions"))).scalar_one()
    return PushConfig(
        enabled=settings.push_configured,
        public_key=settings.vapid_public_key or None,
        devices=int(n),
    )


@router.post("/subscribe", dependencies=[DemoKey])
async def subscribe(body: SubscriptionIn, request: Request, engine: EngineDep) -> dict[str, bool]:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO push_subscriptions (endpoint, keys, user_agent)
                   VALUES (:e, CAST(:k AS jsonb), :ua)
                   ON CONFLICT (endpoint) DO UPDATE SET keys = EXCLUDED.keys"""
            ),
            {
                "e": body.endpoint,
                "k": body.keys.model_dump_json(),
                "ua": (request.headers.get("user-agent") or "")[:300],
            },
        )
    return {"ok": True}


@router.post("/unsubscribe", dependencies=[DemoKey])
async def unsubscribe(body: SubscriptionIn, engine: EngineDep) -> dict[str, bool]:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM push_subscriptions WHERE endpoint = :e"), {"e": body.endpoint}
        )
    return {"ok": True}


@router.post("/test", dependencies=[DemoKey])
async def test_push(engine: EngineDep, settings: SettingsDep) -> dict[str, int]:
    if not settings.push_configured:
        raise HTTPException(503, "Push is not configured (VAPID keys missing)")
    delivered, devices = await send_to_all(
        engine,
        settings,
        payload(
            "SugarScout is connected",
            f"Alerts about {settings.demo_child_name} will appear here.",
            tag="test",
            urgent=False,
        ),
        urgent=False,
    )
    return {"delivered": delivered, "devices": devices}
