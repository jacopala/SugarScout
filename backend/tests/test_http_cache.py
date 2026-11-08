"""Polled JSON: gzip, ETag revalidation (304), and CORS headers on a 304."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.api.http_cache import _matches, etag_for
from sugarscout.api.main import create_app
from sugarscout.demo import DEMO_CHILD_ID, ensure_demo_child
from sugarscout.settings import Settings

ORIGIN = "http://localhost:5173"


@pytest.fixture
async def client(
    settings: Settings, engine: AsyncEngine, redis: Redis
) -> AsyncIterator[AsyncClient]:
    await redis.flushdb()
    await ensure_demo_child(engine, settings)
    app = create_app(settings.model_copy(update={"cors_origins": ORIGIN}))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM alerts WHERE child_id = :c"), {"c": DEMO_CHILD_ID})


async def test_unchanged_json_revalidates_with_304(client: AsyncClient) -> None:
    first = await client.get("/alerts")
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag.startswith('W/"')
    assert first.headers["cache-control"] == "no-cache"

    again = await client.get("/alerts", headers={"If-None-Match": etag, "Origin": ORIGIN})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    assert again.headers["access-control-allow-origin"] == ORIGIN


async def test_changed_json_gets_a_new_etag(client: AsyncClient) -> None:
    before = (await client.get("/alerts")).headers["etag"]
    await client.post("/help")
    after = await client.get("/alerts", headers={"If-None-Match": before})
    assert after.status_code == 200
    assert after.headers["etag"] != before
    assert after.json()[0]["rule_type"] == "help_request"


async def test_large_json_is_gzipped(client: AsyncClient) -> None:
    r = await client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert len(r.content) > 1024
    assert r.headers.get("content-encoding") == "gzip"
    assert r.json()["info"]["title"] == "SugarScout API"


async def test_small_json_is_not_gzipped(client: AsyncClient) -> None:
    r = await client.get("/healthz", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert "content-encoding" not in r.headers


async def test_writes_are_not_cached(client: AsyncClient) -> None:
    r = await client.post("/help")
    assert "etag" not in r.headers


def test_weak_etag_matching() -> None:
    tag = etag_for(b"[]")
    assert _matches(tag, tag)
    assert _matches(tag.removeprefix("W/"), tag)
    assert _matches(f'"other", {tag}', tag)
    assert _matches("*", tag)
    assert not _matches('W/"other"', tag)
