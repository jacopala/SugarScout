"""Mood check-ins: the child's "How are you feeling today?" answers on a 1-5 scale.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE mood_checkins (
          id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          child_id    uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
          mood        smallint NOT NULL CHECK (mood BETWEEN 1 AND 5),
          source      text NOT NULL DEFAULT 'tap' CHECK (source IN ('tap', 'voice')),
          created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX mood_checkins_child_idx ON mood_checkins (child_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mood_checkins")
