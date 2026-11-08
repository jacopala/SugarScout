from __future__ import annotations

from typing import Any

from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.api.main import create_app
from sugarscout.settings import Settings
from sugarscout.worker.main import heartbeat


async def test_healthz(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["x-request-id"]


async def test_readyz_all_dependencies_up(client: AsyncClient, redis: Redis) -> None:
    r = await client.get("/readyz")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["timescaledb"]["ok"] is True
    assert body["timescaledb"]["detail"].startswith("timescaledb 2.")
    assert body["redis"]["ok"] is True


async def test_readyz_reports_worker_heartbeat_age(
    client: AsyncClient, settings: Settings, engine: AsyncEngine, redis: Redis
) -> None:
    ctx: dict[str, Any] = {"engine": engine, "redis": redis, "settings": settings}
    await heartbeat(ctx)

    body = (await client.get("/readyz")).json()
    hb = body["worker_heartbeat"]
    assert hb["last_seen"] is not None
    assert 0 <= hb["age_s"] < 5


async def test_readyz_degraded_when_redis_unreachable(settings: Settings, migrated_db: str) -> None:
    bad = settings.model_copy(update={"redis_url": "redis://127.0.0.1:1/0"})
    app = create_app(bad)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["redis"]["ok"] is False
    assert body["database"]["ok"] is True


async def test_readyz_degraded_when_database_unreachable(settings: Settings, redis: Redis) -> None:
    bad = settings.model_copy(
        update={"database_url": "postgresql://nobody:x@127.0.0.1:1/nope", "db_pool_timeout_s": 1.0}
    )
    app = create_app(bad)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["database"]["ok"] is False
    assert body["redis"]["ok"] is True
