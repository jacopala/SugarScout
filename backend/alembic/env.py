"""Alembic environment: async engine built from application Settings.

Run as a release step (Render pre-deploy command) and locally via the `migrate`
docker-compose service or `uv run alembic upgrade head`.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

import sugarscout.models  # noqa: F401  (register models on Base.metadata)
from sugarscout.db import Base, create_engine
from sugarscout.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata

# TimescaleDB creates internal objects (chunks, materialization hypertables) that
# autogenerate must never try to drop.
_TIMESCALE_SCHEMAS = {"_timescaledb_internal", "_timescaledb_catalog", "_timescaledb_cache"}


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    if type_ == "table" and reflected and compare_to is None:
        # Reflected-only tables (e.g. continuous aggregate internals) are not ours to manage.
        return False
    schema = getattr(obj, "schema", None)
    return schema not in _TIMESCALE_SCHEMAS


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    settings = get_settings().model_copy(update={"service_name": "migrate", "db_pool_size": 1})
    engine = create_engine(settings)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported; Timescale DDL needs a live DB.")

asyncio.run(run_migrations_online())
