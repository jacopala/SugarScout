"""Glucose readings hypertable, hourly/daily continuous aggregates, columnstore policy.

Implements design doc Sections 18.2 to 18.4. Written for TimescaleDB 2.30.x (the
version pinned in docker-compose.yml); the Tiger Cloud service must run a matching
version (Section 19.5).

Band edges (54 / 70 / 180 / 250 mg/dL) are the doc's placeholders and must be
confirmed with the care team before the pilot. Changing them later means
recreating both aggregates in a new migration.

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # Section 18.2. PK includes the time column (hypertable requirement) and serves the
    # rules engine's "latest readings for one child" range scan.
    op.execute(
        """
        CREATE TABLE glucose_readings (
          child_id    uuid        NOT NULL,
          ts          timestamptz NOT NULL,
          value_mg_dl integer     NOT NULL,
          trend       text,
          source      text        NOT NULL,
          PRIMARY KEY (child_id, ts),
          CONSTRAINT glucose_readings_value_range CHECK (value_mg_dl BETWEEN 20 AND 600)
        )
        """
    )
    op.execute("SELECT create_hypertable('glucose_readings', by_range('ts', INTERVAL '7 days'))")

    # Section 18.4. Columnstore (compression) after ~30 days, segmented per child so
    # per-child reads and per-child deletion stay cheap.
    op.execute(
        """
        ALTER TABLE glucose_readings SET (
          timescaledb.enable_columnstore = true,
          timescaledb.segmentby = 'child_id',
          timescaledb.orderby = 'ts DESC'
        )
        """
    )
    op.execute("CALL add_columnstore_policy('glucose_readings', after => INTERVAL '30 days')")

    # Continuous aggregates cannot be created inside a transaction block.
    with op.get_context().autocommit_block():
        # Section 18.3, plus sum_mg_dl so the daily rollup can compute an exact
        # reading-weighted mean instead of an average of hourly averages.
        op.execute(
            """
            CREATE MATERIALIZED VIEW glucose_hourly
            WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
            SELECT child_id,
                   time_bucket(INTERVAL '1 hour', ts) AS bucket,
                   avg(value_mg_dl)  AS avg_mg_dl,
                   sum(value_mg_dl)  AS sum_mg_dl,
                   min(value_mg_dl)  AS min_mg_dl,
                   max(value_mg_dl)  AS max_mg_dl,
                   count(*)          AS n,
                   count(*) FILTER (WHERE value_mg_dl < 54)                AS n_urgent_low,
                   count(*) FILTER (WHERE value_mg_dl BETWEEN 54 AND 69)   AS n_low,
                   count(*) FILTER (WHERE value_mg_dl BETWEEN 70 AND 180)  AS n_target,
                   count(*) FILTER (WHERE value_mg_dl BETWEEN 181 AND 250) AS n_high,
                   count(*) FILTER (WHERE value_mg_dl > 250)               AS n_very_high
            FROM glucose_readings
            GROUP BY child_id, bucket
            WITH NO DATA
            """
        )

        # Hierarchical aggregate on top of the hourly one, for month and quarter views.
        op.execute(
            """
            CREATE MATERIALIZED VIEW glucose_daily
            WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
            SELECT child_id,
                   time_bucket(INTERVAL '1 day', bucket) AS bucket,
                   sum(sum_mg_dl)::numeric / NULLIF(sum(n), 0) AS avg_mg_dl,
                   sum(sum_mg_dl)    AS sum_mg_dl,
                   min(min_mg_dl)    AS min_mg_dl,
                   max(max_mg_dl)    AS max_mg_dl,
                   sum(n)            AS n,
                   sum(n_urgent_low) AS n_urgent_low,
                   sum(n_low)        AS n_low,
                   sum(n_target)     AS n_target,
                   sum(n_high)       AS n_high,
                   sum(n_very_high)  AS n_very_high
            FROM glucose_hourly
            GROUP BY child_id, time_bucket(INTERVAL '1 day', bucket)
            WITH NO DATA
            """
        )

    # Refresh windows cover the last few days so ordinary late CGM data is picked up.
    # Backfills older than these windows need a manual refresh_continuous_aggregate call
    # (Section 18.3); the Phase 3 backfill job will do that.
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('glucose_hourly',
          start_offset => INTERVAL '3 days',
          end_offset => INTERVAL '1 hour',
          schedule_interval => INTERVAL '15 minutes')
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('glucose_daily',
          start_offset => INTERVAL '7 days',
          end_offset => INTERVAL '1 day',
          schedule_interval => INTERVAL '1 hour')
        """
    )

    # Lookup paths for dashboard week/month/quarter views.
    op.execute("CREATE INDEX glucose_hourly_child_bucket_idx ON glucose_hourly (child_id, bucket)")
    op.execute("CREATE INDEX glucose_daily_child_bucket_idx ON glucose_daily (child_id, bucket)")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS glucose_daily")
        op.execute("DROP MATERIALIZED VIEW IF EXISTS glucose_hourly")
    # Dropping the hypertable also removes its columnstore policy job.
    op.execute("DROP TABLE IF EXISTS glucose_readings")
    # The timescaledb extension is left installed on purpose.
