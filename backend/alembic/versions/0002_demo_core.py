"""Demo core tables: children, alerts, notifications, chat messages, summaries.

Plain Postgres tables (relational, low volume; Section 18.2). Hackathon scope: a
single demo child, no users/devices/contacts yet.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE children (
          id          uuid PRIMARY KEY,
          first_name  text NOT NULL,
          age_band    text NOT NULL,
          created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE alerts (
          id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          child_id        uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
          rule_type       text NOT NULL,
          severity        text NOT NULL CHECK (severity IN ('urgent', 'warning', 'info')),
          state           text NOT NULL DEFAULT 'open'
                            CHECK (state IN ('open', 'acknowledged', 'resolved')),
          message         text NOT NULL,
          trigger_data    jsonb NOT NULL DEFAULT '{}'::jsonb,
          opened_at       timestamptz NOT NULL DEFAULT now(),
          acknowledged_at timestamptz,
          resolved_at     timestamptz
        )
        """
    )
    # One open (or acknowledged) alert per rule per child: an episode is updated, not re-sent.
    op.execute(
        """CREATE UNIQUE INDEX alerts_one_active_per_rule
           ON alerts (child_id, rule_type) WHERE state <> 'resolved'"""
    )
    op.execute("CREATE INDEX alerts_child_opened_idx ON alerts (child_id, opened_at DESC)")

    op.execute(
        """
        CREATE TABLE notifications (
          id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          alert_id            bigint NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
          channel             text NOT NULL CHECK (channel IN ('dashboard', 'sms')),
          kind                text NOT NULL CHECK (kind IN ('opened', 'resolved')),
          recipient           text,
          body                text NOT NULL,
          status              text NOT NULL DEFAULT 'queued'
                                CHECK (status IN ('queued', 'sent', 'failed', 'dry_run', 'skipped')),
          provider_message_id text,
          error               text,
          created_at          timestamptz NOT NULL DEFAULT now(),
          sent_at             timestamptz
        )
        """
    )
    op.execute("CREATE INDEX notifications_alert_idx ON notifications (alert_id)")

    op.execute(
        """
        CREATE TABLE chat_messages (
          id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          child_id    uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
          role        text NOT NULL CHECK (role IN ('child', 'companion')),
          content     text NOT NULL,
          flagged     text CHECK (flagged IN ('emergency', 'filtered', 'fallback')),
          created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX chat_messages_child_idx ON chat_messages (child_id, created_at DESC)")

    op.execute(
        """
        CREATE TABLE summaries (
          id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          child_id      uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
          period_start  timestamptz NOT NULL,
          period_end    timestamptz NOT NULL,
          model         text,
          stats         jsonb NOT NULL,
          content       jsonb,
          status        text NOT NULL CHECK (status IN ('ok', 'rejected', 'error', 'disabled')),
          error         text,
          created_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX summaries_child_idx ON summaries (child_id, created_at DESC)")


def downgrade() -> None:
    for table in ("summaries", "chat_messages", "notifications", "alerts", "children"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
