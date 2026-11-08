"""Meals the child reports ("What did you eat?"), with AI sugar/gluten estimates.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE meals (
          id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          child_id         uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
          description      text NOT NULL,
          source           text NOT NULL DEFAULT 'text' CHECK (source IN ('voice', 'tap', 'text')),
          analysis_status  text NOT NULL DEFAULT 'pending'
                             CHECK (analysis_status IN ('pending', 'ok', 'rejected', 'error', 'disabled')),
          analysis         jsonb,
          model            text,
          created_at       timestamptz NOT NULL DEFAULT now(),
          analyzed_at      timestamptz
        )
        """
    )
    op.execute("CREATE INDEX meals_child_idx ON meals (child_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS meals")
