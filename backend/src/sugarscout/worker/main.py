"""ARQ worker.

Jobs:
- `heartbeat` (every minute): proves the worker is alive and the database reachable.
- `cgm_tick` (every SIM_TICK_SECONDS): fake CGM reading, rules on raw data, alert sync.
  Rules run even during a sensor dropout, which is how data gaps get caught.
- `send_sms` (enqueued): Twilio delivery, off the tick's critical path.

Run with: arq sugarscout.worker.main.WorkerSettings
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text

from sugarscout.ai.gateway import get_gateway
from sugarscout.ai.meals import analyze_meal as run_meal_analysis
from sugarscout.db import create_engine
from sugarscout.demo import DEMO_CHILD_ID, ensure_demo_child, ensure_history
from sugarscout.log import configure_logging, get_logger
from sugarscout.notify.push import deliver_pending as deliver_pending_push
from sugarscout.notify.sms import deliver
from sugarscout.settings import get_settings
from sugarscout.sim.tick import run_tick

log = get_logger(__name__)

HEARTBEAT_TTL_S = 10 * 60


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings().model_copy(update={"service_name": "worker"})
    configure_logging(settings, configure_stdlib=False)
    ctx["settings"] = settings
    ctx["engine"] = create_engine(settings)
    ctx["rng"] = random.Random()
    ctx["llm"] = get_gateway(settings)
    await ensure_demo_child(ctx["engine"], settings)
    await ensure_history(ctx["engine"], settings)
    log.info("worker.startup", sim_enabled=settings.sim_enabled, tick_s=settings.sim_tick_seconds)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()
    log.info("worker.shutdown")


async def heartbeat(ctx: dict[str, Any]) -> str:
    """Record that the worker is alive. Only writes the heartbeat if the DB is reachable,
    so a stale heartbeat covers both a stalled worker and a database outage."""
    now = datetime.now(UTC)
    async with ctx["engine"].connect() as conn:
        await conn.execute(text("SELECT 1"))
    await ctx["redis"].set(
        ctx["settings"].worker_heartbeat_key, now.isoformat(), ex=HEARTBEAT_TTL_S
    )
    log.info("worker.heartbeat", at=now.isoformat())
    return now.isoformat()


async def cgm_tick(ctx: dict[str, Any]) -> int | None:
    settings = ctx["settings"]
    if not settings.sim_enabled:
        return None
    value, events, sms_ids = await run_tick(
        ctx["engine"], ctx["redis"], settings, DEMO_CHILD_ID, settings.demo_child_name, ctx["rng"]
    )
    for nid in sms_ids:
        await ctx["redis"].enqueue_job("send_sms", nid)
    for ev in events:
        log.info("alert." + ev.kind, alert_id=ev.alert_id, rule=ev.rule_type)
    return value


async def send_sms(ctx: dict[str, Any], notification_id: int) -> str:
    return await deliver(ctx["engine"], ctx["settings"], notification_id)


async def push_outbox(ctx: dict[str, Any]) -> int:
    """Deliver queued browser pushes (every alert open/resolve queues one)."""
    s = ctx["settings"]
    return await deliver_pending_push(ctx["engine"], s, s.demo_child_name)


async def analyze_meal(ctx: dict[str, Any], meal_id: int) -> str:
    return await run_meal_analysis(ctx["engine"], ctx["settings"], ctx["llm"], meal_id)


_TICK_SECONDS = set(range(0, 60, max(1, get_settings().sim_tick_seconds)))


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
    on_startup = startup
    on_shutdown = shutdown
    functions: ClassVar[list[Any]] = [send_sms, analyze_meal]
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, second=0, run_at_startup=True, timeout=30, unique=True),  # every minute
        cron(cgm_tick, second=_TICK_SECONDS, timeout=10, unique=True, keep_result=0),
        cron(push_outbox, second=set(range(0, 60, 2)), timeout=20, unique=True, keep_result=0),
    ]
    max_jobs = 10
    health_check_interval = 30
