"""Section 18.6 query budgets, measured with EXPLAIN ANALYZE on a realistic data set.

Seeds 5 children x 90 days of 5-minute readings (~130k rows), moves chunks older than
30 days into the columnstore as the policy would, refreshes the aggregates, then times
each dashboard/rules query. Execution time is server-side; wall time adds the network
round trip, which is what the Tiger Cloud staging run is meant to expose.

Chat context assembly (also in 18.6) needs Phase 2 and 5 tables and is not covered yet.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.dev.seed import child_ids, clear, seed
from tests.conftest import BUDGET_MULTIPLIER, record_budget

pytestmark = pytest.mark.budget

CHILDREN = 5
DAYS = 90
RULES_BUDGET_MS = 50.0
VIEW_BUDGET_MS = 50.0  # the doc only asks for "one query"; 50 ms keeps dashboards snappy


@pytest.fixture(scope="module")
async def seeded(engine: AsyncEngine) -> AsyncIterator[uuid.UUID]:
    await seed(engine, CHILDREN, DAYS, refresh=False)
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        chunks = (
            (
                await conn.execute(
                    text(
                        """SELECT c FROM show_chunks('glucose_readings',
                                                 older_than => INTERVAL '30 days') c"""
                    )
                )
            )
            .scalars()
            .all()
        )
        for chunk in chunks:
            await conn.execute(
                text(
                    "CALL convert_to_columnstore(CAST(:c AS regclass), if_not_columnstore => true)"
                ),
                {"c": chunk},
            )
        await conn.execute(text("CALL refresh_continuous_aggregate('glucose_hourly', NULL, NULL)"))
        await conn.execute(text("CALL refresh_continuous_aggregate('glucose_daily', NULL, NULL)"))
        await conn.execute(text("ANALYZE glucose_readings"))
    yield child_ids(CHILDREN)[2]
    await clear(engine)


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    out = [node]
    for child in node.get("Plans", []):
        out.extend(_walk(child))
    return out


async def _measure(
    engine: AsyncEngine, name: str, sql: str, params: dict[str, Any], budget_ms: float
) -> tuple[dict[str, Any], int]:
    async with engine.connect() as conn:
        # Warm the connection and plan cache once, as a pooled production connection would be.
        await conn.execute(text(sql), params)

        start = time.perf_counter()
        rows = (await conn.execute(text(sql), params)).all()
        wall_ms = (time.perf_counter() - start) * 1000

        explain = (
            await conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"), params)
        ).scalar_one()

    plan = explain[0]
    exec_ms = float(plan["Execution Time"])
    limit = budget_ms * BUDGET_MULTIPLIER
    record_budget(
        {
            "name": name,
            "rows": len(rows),
            "exec_ms": exec_ms,
            "wall_ms": wall_ms,
            "budget_ms": limit,
            "ok": exec_ms < limit,
        }
    )
    assert exec_ms < limit, f"{name}: {exec_ms:.2f} ms exceeds budget {limit:.1f} ms"
    return plan["Plan"], len(rows)


async def test_rules_window_last_3h(engine: AsyncEngine, seeded: uuid.UUID) -> None:
    plan, n = await _measure(
        engine,
        "rules: raw last 3h, one child",
        """SELECT ts, value_mg_dl, trend FROM glucose_readings
           WHERE child_id = :c AND ts >= now() - INTERVAL '3 hours'
           ORDER BY ts""",
        {"c": seeded},
        RULES_BUDGET_MS,
    )
    assert 35 <= n <= 37
    # Must be an indexed range scan on recent chunks, never a sequential scan.
    seq_scans = [p for p in _walk(plan) if p["Node Type"] == "Seq Scan"]
    assert not seq_scans, f"rules query uses a sequential scan: {seq_scans}"


async def test_dashboard_day_view_raw(engine: AsyncEngine, seeded: uuid.UUID) -> None:
    _, n = await _measure(
        engine,
        "dashboard day: raw 24h",
        """SELECT ts, value_mg_dl, trend FROM glucose_readings
           WHERE child_id = :c AND ts >= now() - INTERVAL '24 hours'
           ORDER BY ts""",
        {"c": seeded},
        VIEW_BUDGET_MS,
    )
    assert 285 <= n <= 289


@pytest.mark.parametrize(
    ("label", "days", "lo", "hi"), [("week", 7, 167, 169), ("month", 30, 719, 721)]
)
async def test_dashboard_week_and_month_from_hourly(
    engine: AsyncEngine, seeded: uuid.UUID, label: str, days: int, lo: int, hi: int
) -> None:
    _, n = await _measure(
        engine,
        f"dashboard {label}: hourly aggregate",
        """SELECT bucket, avg_mg_dl, min_mg_dl, max_mg_dl, n,
                  n_urgent_low, n_low, n_target, n_high, n_very_high
           FROM glucose_hourly
           WHERE child_id = :c AND bucket >= now() - make_interval(days => :d)
           ORDER BY bucket""",
        {"c": seeded, "d": days},
        VIEW_BUDGET_MS,
    )
    assert lo <= n <= hi


async def test_dashboard_quarter_from_daily(engine: AsyncEngine, seeded: uuid.UUID) -> None:
    _, n = await _measure(
        engine,
        "dashboard quarter: daily aggregate",
        """SELECT bucket, avg_mg_dl, min_mg_dl, max_mg_dl, n,
                  n_urgent_low, n_low, n_target, n_high, n_very_high
           FROM glucose_daily
           WHERE child_id = :c AND bucket >= now() - INTERVAL '90 days'
           ORDER BY bucket""",
        {"c": seeded},
        VIEW_BUDGET_MS,
    )
    assert 90 <= n <= 92
