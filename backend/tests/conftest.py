"""Shared test fixtures.

By default tests create (and drop) a throwaway database `sugarscout_test` on the local
TimescaleDB from docker-compose, and use Redis DB 15.

To run the query-budget tests against an existing database such as the Tiger Cloud
staging service, point TEST_DATABASE_URL at it and set TEST_EXTERNAL_DB=1. The
harness then never creates or drops the database, skips destructive tests (migration
round-trip), and only removes the rows it seeded:

    TEST_DATABASE_URL=postgres://... TEST_EXTERNAL_DB=1 DB_SSL_MODE=require \
      uv run pytest -m budget
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.db import create_engine
from sugarscout.settings import Settings, get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://sugarscout:sugarscout@localhost:55432/sugarscout_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
EXTERNAL_DB = os.environ.get("TEST_EXTERNAL_DB") == "1"

# Section 18.6 query budgets are measured as server-side execution time. CI runners
# are noisy shared machines, so CI may loosen them with BUDGET_MULTIPLIER; the real
# gate measurement is a run against Tiger Cloud staging with the multiplier at 1.
BUDGET_MULTIPLIER = float(os.environ.get("BUDGET_MULTIPLIER", "1"))

external_only_skip = pytest.mark.skipif(EXTERNAL_DB, reason="destructive; skipped on external DB")

_budget_results: list[dict[str, Any]] = []


def record_budget(result: dict[str, Any]) -> None:
    _budget_results.append(result)


def pytest_terminal_summary(terminalreporter: Any) -> None:
    if not _budget_results:
        return
    tr = terminalreporter
    tr.section("Section 18.6 query budget")
    tr.write_line(
        f"{'operation':<34}{'rows':>6}{'exec ms':>10}{'wall ms':>10}{'budget ms':>11}  result"
    )
    for r in _budget_results:
        tr.write_line(
            f"{r['name']:<34}{r['rows']:>6}{r['exec_ms']:>10.2f}{r['wall_ms']:>10.2f}"
            f"{r['budget_ms']:>11.1f}  {'PASS' if r['ok'] else 'FAIL'}"
        )
    if BUDGET_MULTIPLIER != 1:
        tr.write_line(f"(budgets multiplied by BUDGET_MULTIPLIER={BUDGET_MULTIPLIER})")


def _admin_and_name(url: str) -> tuple[str, str]:
    base, _, name = url.rpartition("/")
    return f"{base}/postgres", name.split("?")[0]


async def _recreate_database(url: str) -> None:
    admin_url, name = _admin_and_name(url)
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def _drop_database(url: str) -> None:
    admin_url, name = _admin_and_name(url)
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


def alembic_config() -> Config:
    return Config(str(BACKEND_DIR / "alembic.ini"))


@pytest.fixture(scope="session")
def settings() -> Iterator[Settings]:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["REDIS_URL"] = TEST_REDIS_URL
    os.environ.setdefault("ENV", "test")
    os.environ.setdefault("LOG_JSON", "false")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def migrated_db(settings: Settings) -> Iterator[str]:
    """A database at Alembic head. Sync fixture: alembic's env.py runs its own event loop."""
    if not EXTERNAL_DB:
        asyncio.run(_recreate_database(TEST_DATABASE_URL))
    command.upgrade(alembic_config(), "head")
    yield TEST_DATABASE_URL
    if not EXTERNAL_DB:
        asyncio.run(_drop_database(TEST_DATABASE_URL))


@pytest.fixture(scope="session")
async def engine(settings: Settings, migrated_db: str) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(settings.model_copy(update={"service_name": "test"}))
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(str(settings.redis_url))
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def client(settings: Settings, migrated_db: str) -> AsyncIterator[AsyncClient]:
    from sugarscout.api.main import create_app

    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c
