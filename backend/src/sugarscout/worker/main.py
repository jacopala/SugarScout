"""ARQ worker.

Phase 1 runs a single cron job, `heartbeat`, which proves the worker is alive and
can reach both Redis and the database. Phase 3 adds CGM polling; Phase 4 adds rules
evaluation and the dead-man's switch that pages when this heartbeat goes stale or
the database is unreachable (Section 18.7).

Run with: arq sugarscout.worker.main.WorkerSettings
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text

from sugarscout.db import create_engine
from sugarscout.log import configure_logging, get_logger
from sugarscout.settings import get_settings

log = get_logger(__name__)

HEARTBEAT_TTL_S = 10 * 60


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings().model_copy(update={"service_name": "worker"})
    configure_logging(settings, configure_stdlib=False)
    ctx["settings"] = settings
    ctx["engine"] = create_engine(settings)
    log.info("worker.startup")


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


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
    on_startup = startup
    on_shutdown = shutdown
    functions: ClassVar[list[Any]] = []
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, second=0, run_at_startup=True, timeout=30, unique=True),  # every minute
    ]
    max_jobs = 10
    health_check_interval = 30
