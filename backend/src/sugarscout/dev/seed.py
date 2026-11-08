"""Minimal deterministic glucose seeder for local development and query-budget tests.

This is NOT the Phase 3 synthetic glucose generator (which models meals, insulin, and
sensor faults). It produces a plausible-looking diurnal curve with deterministic noise,
generated server-side so seeding ~130k rows takes a second or two.

    uv run python -m sugarscout.dev.seed --children 5 --days 90
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.db import create_engine
from sugarscout.settings import get_settings

SEED_SOURCE = "dev-seed"

# Fixed namespace so the same --children count always yields the same child ids.
_NS = uuid.UUID("5b0c6f3e-2d1a-4c55-9b2e-6a1f0d7c8e90")


def child_ids(count: int) -> list[uuid.UUID]:
    return [uuid.uuid5(_NS, f"child-{i}") for i in range(count)]


_INSERT = text(
    """
    INSERT INTO glucose_readings (child_id, ts, value_mg_dl, trend, source)
    SELECT c.child_id,
           g.ts,
           -- diurnal swing + per-child offset + deterministic noise, clamped to sensor range
           LEAST(400, GREATEST(40, round(
               140
               + 55 * sin(extract(epoch FROM g.ts) / 86400.0 * 2 * pi() + c.ord)
               + 25 * sin(extract(epoch FROM g.ts) / 10800.0 * 2 * pi())
               + (abs(hashtext(c.child_id::text || g.ts::text)) % 41) - 20
           )))::int,
           'flat',
           :source
    FROM unnest(CAST(:child_ids AS uuid[])) WITH ORDINALITY AS c(child_id, ord)
    CROSS JOIN generate_series(
        date_trunc('minute', now()) - make_interval(days => :days),
        date_trunc('minute', now()),
        INTERVAL '5 minutes'
    ) AS g(ts)
    ON CONFLICT (child_id, ts) DO NOTHING
    """
)


async def seed(engine: AsyncEngine, children: int, days: int, refresh: bool = True) -> int:
    ids = child_ids(children)
    async with engine.begin() as conn:
        result = await conn.execute(
            _INSERT, {"child_ids": [str(i) for i in ids], "days": days, "source": SEED_SOURCE}
        )
        inserted = result.rowcount or 0
    if refresh:
        await refresh_aggregates(engine)
    return inserted


async def refresh_aggregates(engine: AsyncEngine) -> None:
    """Refresh both aggregates over all time. Needed after any backfill older than the
    policy windows (Section 18.3). refresh_continuous_aggregate cannot run in a transaction."""
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("CALL refresh_continuous_aggregate('glucose_hourly', NULL, NULL)"))
        await conn.execute(text("CALL refresh_continuous_aggregate('glucose_daily', NULL, NULL)"))


async def clear(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM glucose_readings WHERE source = :s"), {"s": SEED_SOURCE}
        )
    await refresh_aggregates(engine)


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--children", type=int, default=5)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--clear", action="store_true", help="delete seeded rows instead")
    args = parser.parse_args()

    engine = create_engine(get_settings().model_copy(update={"service_name": "seed"}))
    try:
        if args.clear:
            await clear(engine)
            print("cleared seeded readings")
        else:
            n = await seed(engine, args.children, args.days)
            print(f"inserted {n} readings for {args.children} children over {args.days} days")
            for cid in child_ids(args.children):
                print(f"  child_id {cid}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
