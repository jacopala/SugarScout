"""Scout agent: push subscriptions, forecasts, insulin log, agent questions & decisions,
mood context, and the push notification channel.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Notifications can now go to browser push as well.
    op.execute("ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_channel_check")
    op.execute(
        """ALTER TABLE notifications ADD CONSTRAINT notifications_channel_check
           CHECK (channel IN ('dashboard', 'sms', 'push'))"""
    )

    op.execute(
        """
        CREATE TABLE push_subscriptions (
          id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          endpoint    text NOT NULL UNIQUE,
          keys        jsonb NOT NULL,
          user_agent  text,
          created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # Every short-term forecast, scored later against what actually happened.
    op.execute(
        """
        CREATE TABLE forecasts (
          id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          child_id     uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
          made_at      timestamptz NOT NULL,
          target_at    timestamptz NOT NULL,
          horizon_min  integer NOT NULL,
          predicted    integer NOT NULL,
          slope_per_5min real NOT NULL,
          actual       integer,
          error        integer
        )
        """
    )
    op.execute("CREATE INDEX forecasts_child_made_idx ON forecasts (child_id, made_at DESC)")
    op.execute("CREATE INDEX forecasts_unscored_idx ON forecasts (target_at) WHERE actual IS NULL")

    # Insulin is only ever recorded and shown, never calculated or suggested.
    op.execute(
        """
        CREATE TABLE insulin_doses (
          id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          child_id   uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
          given_at   timestamptz NOT NULL DEFAULT now(),
          units      numeric(5, 2) CHECK (units IS NULL OR (units > 0 AND units <= 100)),
          kind       text NOT NULL CHECK (kind IN ('meal', 'correction', 'long_acting', 'unknown')),
          source     text NOT NULL CHECK (source IN ('parent', 'child_report')),
          note       text,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX insulin_child_idx ON insulin_doses (child_id, given_at DESC)")

    op.execute(
        """
        CREATE TABLE agent_questions (
          id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          child_id     uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
          question     text NOT NULL,
          wording      text NOT NULL,
          options      jsonb NOT NULL,
          reasons      jsonb NOT NULL DEFAULT '[]'::jsonb,
          meal_id      bigint REFERENCES meals(id) ON DELETE SET NULL,
          asked_at     timestamptz NOT NULL DEFAULT now(),
          expires_at   timestamptz NOT NULL,
          answered_at  timestamptz,
          answer       text
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_questions_child_idx ON agent_questions (child_id, asked_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE agent_decisions (
          id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          child_id    uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
          decided_at  timestamptz NOT NULL DEFAULT now(),
          situation   jsonb NOT NULL,
          eligible    jsonb NOT NULL,
          output      jsonb,
          applied     jsonb NOT NULL,
          model       text,
          status      text NOT NULL CHECK (status IN ('ok', 'overridden', 'fallback', 'idle'))
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_decisions_child_idx ON agent_decisions (child_id, decided_at DESC)"
    )

    op.execute(
        """ALTER TABLE mood_checkins
           ADD COLUMN context text NOT NULL DEFAULT 'daily'
             CHECK (context IN ('daily', 'after_meal', 'agent')),
           ADD COLUMN meal_id bigint REFERENCES meals(id) ON DELETE SET NULL"""
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE mood_checkins DROP COLUMN IF EXISTS meal_id, DROP COLUMN IF EXISTS context"
    )
    for table in (
        "agent_decisions",
        "agent_questions",
        "insulin_doses",
        "forecasts",
        "push_subscriptions",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DELETE FROM notifications WHERE channel = 'push'")
    op.execute("ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_channel_check")
    op.execute(
        """ALTER TABLE notifications ADD CONSTRAINT notifications_channel_check
           CHECK (channel IN ('dashboard', 'sms'))"""
    )
