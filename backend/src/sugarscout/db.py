"""Async SQLAlchemy engine and session factory.

Section 18.6: async pool with pre-ping, sized per service, TLS enforced outside local,
and a server-side statement timeout so a slow query can never hang a request or a
rules evaluation indefinitely.
"""

from __future__ import annotations

import ssl
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from sugarscout.settings import DbSslMode, Settings


class Base(DeclarativeBase):
    pass


def _connect_args(settings: Settings) -> dict[str, Any]:
    args: dict[str, Any] = {
        "server_settings": {
            "statement_timeout": str(settings.db_statement_timeout_ms),
            "application_name": f"sugarscout-{settings.service_name}",
        },
        "timeout": settings.db_pool_timeout_s,
    }
    if settings.db_ssl_mode is DbSslMode.REQUIRE:
        ctx = ssl.create_default_context()  # verifies the server certificate and hostname
        args["ssl"] = ctx
    else:
        args["ssl"] = False
    return args


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.async_database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=_connect_args(settings),
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
