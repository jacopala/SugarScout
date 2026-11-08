"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from sugarscout.api.routes import alerts, demo, glucose, health
from sugarscout.db import create_engine, create_sessionmaker
from sugarscout.log import configure_logging, get_logger
from sugarscout.settings import Settings, get_settings

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        redis = Redis.from_url(str(settings.redis_url), socket_timeout=2, socket_connect_timeout=2)
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.redis = redis
        # ARQ pool for enqueueing jobs (e.g. SMS for chat escalations). Lazily created
        # so the API still starts, and /readyz still reports, when Redis is down.
        app.state.arq = None
        log.info("api.startup")
        try:
            yield
        finally:
            if app.state.arq is not None:
                await app.state.arq.aclose()
            await redis.aclose()
            await engine.dispose()
            log.info("api.shutdown")

    app = FastAPI(title="SugarScout API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["x-request-id"] = request_id
        log.info(
            "http.request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return response

    app.include_router(health.router)
    app.include_router(glucose.router)
    app.include_router(alerts.router)
    app.include_router(demo.router)
    return app


app = create_app()
