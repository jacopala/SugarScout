"""Migration 0001: TimescaleDB objects exist with the intended settings, the aggregates
compute correct numbers, and the migration round-trips."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.dev.seed import refresh_aggregates
from tests.conftest import alembic_config, external_only_skip


async def _scalar(engine: AsyncEngine, sql: str, **params: object) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def test_glucose_readings_is_a_hypertable(engine: AsyncEngine) -> None:
    dims = await _scalar(
        engine,
        """SELECT column_name || ':' || time_interval::text
           FROM timescaledb_information.dimensions WHERE hypertable_name = 'glucose_readings'""",
    )
    assert dims == "ts:7 days"


async def test_primary_key_is_child_then_time(engine: AsyncEngine) -> None:
    cols = await _scalar(
        engine,
        """SELECT string_agg(a.attname, ',' ORDER BY k.ord)
           FROM pg_index i
           JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
           JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
           WHERE i.indrelid = 'glucose_readings'::regclass AND i.indisprimary""",
    )
    assert cols == "child_id,ts"


async def test_continuous_aggregates_are_real_time(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT view_name, materialized_only
                       FROM timescaledb_information.continuous_aggregates ORDER BY view_name"""
                )
            )
        ).all()
    assert [(r.view_name, r.materialized_only) for r in rows] == [
        ("glucose_daily", False),
        ("glucose_hourly", False),
    ]


async def test_policies_registered(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """SELECT proc_name, hypertable_name, config
                       FROM timescaledb_information.jobs
                       WHERE proc_name IN ('policy_compression',
                                           'policy_refresh_continuous_aggregate')"""
                )
            )
        ).all()
    by_target = {(r.proc_name, r.hypertable_name): r.config for r in rows}

    assert by_target[("policy_compression", "glucose_readings")]["compress_after"] == "30 days"
    hourly = by_target[("policy_refresh_continuous_aggregate", "glucose_hourly")]
    assert hourly["start_offset"] == "3 days"
    daily = by_target[("policy_refresh_continuous_aggregate", "glucose_daily")]
    assert daily["start_offset"] == "7 days"


async def test_columnstore_segmented_by_child(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """SELECT segmentby, orderby
                       FROM timescaledb_information.hypertable_columnstore_settings
                       WHERE hypertable = 'glucose_readings'::regclass"""
                )
            )
        ).one()
    assert row.segmentby == "child_id"
    assert row.orderby == "ts DESC"


async def test_value_range_check_rejects_impossible_values(engine: AsyncEngine) -> None:
    import sqlalchemy.exc

    child = uuid.uuid4()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """INSERT INTO glucose_readings (child_id, ts, value_mg_dl, source)
                       VALUES (:c, now(), 5000, 'test')"""
                ),
                {"c": child},
            )
    except sqlalchemy.exc.IntegrityError:
        return
    raise AssertionError("value_mg_dl=5000 should violate the range check")


async def test_daily_average_is_reading_weighted_and_bands_add_up(engine: AsyncEngine) -> None:
    """Two hours with different reading counts: the daily mean must be the mean of all
    readings, not the mean of the two hourly means."""
    child = uuid.uuid4()
    day = datetime(2026, 1, 15, tzinfo=UTC)
    # Hour 0: 11 readings at 50 (urgent low). Hour 1: 1 reading at 300 (very high).
    readings = [(day + timedelta(minutes=5 * i), 50) for i in range(11)]
    readings.append((day + timedelta(hours=1), 300))
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO glucose_readings (child_id, ts, value_mg_dl, source)
                   VALUES (:c, :ts, :v, 'test')"""
            ),
            [{"c": child, "ts": ts, "v": v} for ts, v in readings],
        )
    await refresh_aggregates(engine)

    async with engine.connect() as conn:
        daily = (
            await conn.execute(
                text("SELECT * FROM glucose_daily WHERE child_id = :c"), {"c": child}
            )
        ).one()
        hourly_n = (
            await conn.execute(
                text("SELECT count(*) FROM glucose_hourly WHERE child_id = :c"), {"c": child}
            )
        ).scalar()

    expected_mean = (11 * 50 + 300) / 12  # 70.83, vs 175 for a mean of hourly means
    assert hourly_n == 2
    assert daily.n == 12
    assert abs(float(daily.avg_mg_dl) - expected_mean) < 0.01
    assert (daily.min_mg_dl, daily.max_mg_dl) == (50, 300)
    assert daily.n_urgent_low == 11
    assert daily.n_very_high == 1
    assert daily.n_low + daily.n_target + daily.n_high == 0


async def test_band_edges_are_inclusive_as_documented(engine: AsyncEngine) -> None:
    child = uuid.uuid4()
    hour = datetime(2026, 2, 1, 12, tzinfo=UTC)
    values = [53, 54, 69, 70, 180, 181, 250, 251]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO glucose_readings (child_id, ts, value_mg_dl, source)
                   VALUES (:c, :ts, :v, 'test')"""
            ),
            [
                {"c": child, "ts": hour + timedelta(minutes=5 * i), "v": v}
                for i, v in enumerate(values)
            ],
        )
    await refresh_aggregates(engine)
    async with engine.connect() as conn:
        h = (
            await conn.execute(
                text("SELECT * FROM glucose_hourly WHERE child_id = :c"), {"c": child}
            )
        ).one()
    # 53 | 54,69 | 70,180 | 181,250 | 251
    assert (h.n_urgent_low, h.n_low, h.n_target, h.n_high, h.n_very_high) == (1, 2, 2, 2, 1)


async def test_hourly_aggregate_includes_unrefreshed_recent_readings(engine: AsyncEngine) -> None:
    """Real-time mode: a reading written seconds ago shows up without any refresh."""
    child = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO glucose_readings (child_id, ts, value_mg_dl, source)
                   VALUES (:c, now(), 123, 'test')"""
            ),
            {"c": child},
        )
    n = await _scalar(engine, "SELECT sum(n) FROM glucose_hourly WHERE child_id = :c", c=child)
    assert n == 1


@external_only_skip
def test_migration_round_trip(engine: AsyncEngine) -> None:
    """downgrade base -> upgrade head leaves a working schema. Runs last in this module
    (sync test, so alembic can run its own event loop)."""
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
