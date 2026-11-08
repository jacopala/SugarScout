"""Measure database round-trip time from wherever this runs (Section 19.2, Phase 0/1).

Run it from a Render shell in each candidate region against the Tiger Cloud service:

    DATABASE_URL=... DB_SSL_MODE=require uv run python scripts/rtt.py --samples 50

Reports connection setup time and SELECT 1 round-trip percentiles over one pooled
connection, which is what the API and worker pay per query.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

from sqlalchemy import text

from sugarscout.db import create_engine
from sugarscout.settings import get_settings


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


async def main(samples: int) -> None:
    settings = get_settings().model_copy(update={"service_name": "rtt", "db_pool_size": 1})
    engine = create_engine(settings)
    try:
        t0 = time.perf_counter()
        async with engine.connect() as conn:
            connect_ms = (time.perf_counter() - t0) * 1000
            await conn.execute(text("SELECT 1"))  # warm up
            rtts: list[float] = []
            for _ in range(samples):
                s = time.perf_counter()
                await conn.execute(text("SELECT 1"))
                rtts.append((time.perf_counter() - s) * 1000)
            server = (await conn.execute(text("SELECT inet_server_addr()::text"))).scalar()
    finally:
        await engine.dispose()

    print(f"target          {settings.async_database_url.split('@')[-1]} ({server})")
    print(f"tls             {settings.db_ssl_mode.value}")
    print(f"connect         {connect_ms:7.1f} ms")
    print(f"SELECT 1 p50    {statistics.median(rtts):7.2f} ms")
    print(f"SELECT 1 p95    {_pct(rtts, 95):7.2f} ms")
    print(f"SELECT 1 max    {max(rtts):7.2f} ms   (n={samples})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=50)
    asyncio.run(main(parser.parse_args().samples))
