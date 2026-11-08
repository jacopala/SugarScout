"""Browser push: subscription, child-specific wording, delivery and pruning (push service mocked)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.api.main import create_app
from sugarscout.demo import DEMO_CHILD_ID, ensure_demo_child
from sugarscout.notify import push as push_mod
from sugarscout.settings import Settings

SUB = {
    "endpoint": "https://push.example.test/sub/abc123",
    "keys": {"p256dh": "BPx" + "a" * 60, "auth": "auth-secret-1"},
}


@pytest.fixture
async def api(
    settings: Settings, engine: AsyncEngine, redis: Redis
) -> AsyncIterator[tuple[AsyncClient, Settings]]:
    await redis.flushdb()
    await ensure_demo_child(engine, settings)
    keyed = settings.model_copy(update={"vapid_public_key": "BPUB", "vapid_private_key": "PRIV"})
    app = create_app(keyed)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c, keyed
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM push_subscriptions"))
        await conn.execute(text("DELETE FROM alerts WHERE child_id = :c"), {"c": DEMO_CHILD_ID})


async def test_subscribe_and_config(api: tuple[AsyncClient, Settings]) -> None:
    c, _ = api
    assert (await c.post("/push/subscribe", json=SUB)).status_code == 200
    assert (await c.post("/push/subscribe", json=SUB)).status_code == 200  # idempotent
    cfg = (await c.get("/push/config")).json()
    assert cfg == {"enabled": True, "public_key": "BPUB", "devices": 1}


async def test_alert_push_carries_child_specific_text_and_prunes_dead_devices(
    api: tuple[AsyncClient, Settings], engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, keyed = api
    await c.post("/push/subscribe", json=SUB)
    dead = {**SUB, "endpoint": "https://push.example.test/sub/gone"}
    await c.post("/push/subscribe", json=dead)

    sent: list[dict[str, Any]] = []

    def fake_send(settings: Settings, sub: dict[str, Any], data: str, urgent: bool) -> int:
        sent.append({"endpoint": sub["endpoint"], **json.loads(data), "urgent_hdr": urgent})
        return 410 if sub["endpoint"].endswith("gone") else 201

    monkeypatch.setattr(push_mod, "_send_one", fake_send)

    await c.post("/help")  # opens an urgent help_request alert -> queues a push
    processed = await push_mod.deliver_pending(engine, keyed, "Alex")
    assert processed == 1

    good = next(s for s in sent if s["endpoint"] == SUB["endpoint"])
    assert good["title"] == "Urgent: Alex · help request"
    assert "Alex pressed the Help button" in good["body"]
    assert "System downtime" not in good["body"]
    assert good["urgent"] is True

    async with engine.connect() as conn:
        status = (
            await conn.execute(
                text(
                    "SELECT status FROM notifications WHERE channel = 'push' ORDER BY id DESC LIMIT 1"
                )
            )
        ).scalar_one()
        devices = (await conn.execute(text("SELECT count(*) FROM push_subscriptions"))).scalar_one()
    assert status == "sent"
    assert devices == 1, "a 410 Gone subscription is removed"


async def test_push_without_devices_or_keys_is_not_an_error(
    api: tuple[AsyncClient, Settings], engine: AsyncEngine, settings: Settings
) -> None:
    c, keyed = api
    await c.post("/help")
    await push_mod.deliver_pending(engine, keyed, "Alex")
    async with engine.connect() as conn:
        status = (
            await conn.execute(
                text(
                    "SELECT status, error FROM notifications WHERE channel = 'push' ORDER BY id DESC LIMIT 1"
                )
            )
        ).one()
    assert tuple(status) == ("skipped", "no devices subscribed")


async def test_help_sends_push_immediately(
    api: tuple[AsyncClient, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raising an alert enqueues `push_now`, so the push does not wait for the outbox timer."""
    c, _ = api
    jobs: list[tuple[str, tuple[object, ...]]] = []

    async def fake_enqueue(request: object, job: str, *args: object) -> None:
        jobs.append((job, args))

    monkeypatch.setattr("sugarscout.api.deps.enqueue", fake_enqueue)
    assert (await c.post("/help")).status_code == 200
    assert ("push_now", ()) in jobs


async def test_concurrent_delivery_sends_each_push_once(
    api: tuple[AsyncClient, Settings], engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`push_now` and the outbox timer can overlap; SKIP LOCKED keeps it to one send."""
    import asyncio
    import time

    c, keyed = api
    await c.post("/push/subscribe", json=SUB)
    sent: list[str] = []

    def slow_send(settings: Settings, sub: dict[str, Any], data: str, urgent: bool) -> int:
        time.sleep(0.2)  # hold the row lock while the other runner looks
        sent.append(json.loads(data)["tag"])
        return 201

    monkeypatch.setattr(push_mod, "_send_one", slow_send)
    await c.post("/help")
    counts = await asyncio.gather(
        push_mod.deliver_pending(engine, keyed, "Alex"),
        push_mod.deliver_pending(engine, keyed, "Alex"),
    )
    assert sorted(counts) == [0, 1]
    assert len(sent) == 1
