"""Shared FastAPI dependencies."""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.ai.concern import Concern
from sugarscout.settings import Settings


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def require_demo_key(
    settings: SettingsDep,
    x_demo_key: Annotated[str | None, Header()] = None,
) -> None:
    """Gate for anything that sends texts, spends model credits, or changes state.

    Hackathon stand-in for real auth (Phase 2): one shared access code.
    """
    expected = settings.demo_access_code
    if not expected:
        return
    if not x_demo_key or not secrets.compare_digest(x_demo_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Demo access code required")


DemoKey = Depends(require_demo_key)


async def enqueue(request: Request, job: str, *args: object) -> None:
    """Enqueue an ARQ job from the API, creating the pool on first use."""
    from arq import create_pool
    from arq.connections import RedisSettings

    state = request.app.state
    if state.arq is None:
        state.arq = await create_pool(RedisSettings.from_dsn(str(state.settings.redis_url)))
    await state.arq.enqueue_job(job, *args)


async def deliver_now(request: Request, sms_ids: Iterable[int] = ()) -> None:
    """Send what an alert just queued: each SMS, then the browser pushes right away.

    The worker's push outbox timer is only the retry path, so a push no longer waits
    for its next pass.
    """
    for nid in sms_ids:
        await enqueue(request, "send_sms", nid)
    await enqueue(request, "push_now")


def concern_fields(concern: Concern, settings: Settings) -> dict[str, object]:
    """What the child's screen needs to offer a call. The parent's number goes only
    to callers that passed the access code, and only when a call is suggested."""
    return {
        "concern_level": concern.level,
        "suggest_call": concern.suggest_call,
        "guardian_phone": (settings.parent_phone or None) if concern.suggest_call else None,
    }
