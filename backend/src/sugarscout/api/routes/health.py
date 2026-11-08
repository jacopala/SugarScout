"""Liveness and readiness endpoints.

`/healthz` says the process is up. `/readyz` checks the dependencies the API needs
(database with the TimescaleDB extension, Redis) and reports worker heartbeat age.
Heartbeat age is informational in Phase 1; Phase 4 builds the dead-man's switch on it.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.log import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)

CHECK_TIMEOUT_S = 3.0


class CheckResult(BaseModel):
    ok: bool
    latency_ms: float | None = None
    detail: str | None = None


class HeartbeatInfo(BaseModel):
    last_seen: datetime | None
    age_s: float | None


class ReadyResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: CheckResult
    timescaledb: CheckResult
    redis: CheckResult
    worker_heartbeat: HeartbeatInfo


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _timed(coro: Any) -> tuple[Any, float]:
    start = time.perf_counter()
    result = await asyncio.wait_for(coro, timeout=CHECK_TIMEOUT_S)
    return result, round((time.perf_counter() - start) * 1000, 1)


async def _check_db(engine: AsyncEngine) -> tuple[CheckResult, CheckResult]:
    async def run() -> str | None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            row = await conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            )
            return row.scalar_one_or_none()

    try:
        version, ms = await _timed(run())
    except Exception as exc:
        log.warning("readyz.database_failed", error=repr(exc))
        failed = CheckResult(ok=False, detail="unreachable")
        return failed, CheckResult(ok=False, detail="unknown")
    db = CheckResult(ok=True, latency_ms=ms)
    ts = (
        CheckResult(ok=True, detail=f"timescaledb {version}")
        if version
        else CheckResult(ok=False, detail="extension not installed")
    )
    return db, ts


async def _check_redis(redis: Redis, heartbeat_key: str) -> tuple[CheckResult, HeartbeatInfo]:
    try:
        _, ms = await _timed(redis.ping())
        raw = await redis.get(heartbeat_key)
    except Exception as exc:
        log.warning("readyz.redis_failed", error=repr(exc))
        return CheckResult(ok=False, detail="unreachable"), HeartbeatInfo(
            last_seen=None, age_s=None
        )

    last_seen: datetime | None = None
    age: float | None = None
    if raw is not None:
        last_seen = datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else raw)
        age = round((datetime.now(UTC) - last_seen).total_seconds(), 1)
    return CheckResult(ok=True, latency_ms=ms), HeartbeatInfo(last_seen=last_seen, age_s=age)


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(request: Request, response: Response) -> ReadyResponse:
    state = request.app.state
    (db, ts), (rd, hb) = await asyncio.gather(
        _check_db(state.engine),
        _check_redis(state.redis, state.settings.worker_heartbeat_key),
    )
    ok = db.ok and ts.ok and rd.ok
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ok" if ok else "degraded",
        database=db,
        timescaledb=ts,
        redis=rd,
        worker_heartbeat=hb,
    )
