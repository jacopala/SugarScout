"""Alert inbox state for the parent: read and dismissed (hidden, never deleted from audit).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """ALTER TABLE alerts
           ADD COLUMN read_at timestamptz,
           ADD COLUMN dismissed_at timestamptz"""
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE alerts DROP COLUMN IF EXISTS dismissed_at, DROP COLUMN IF EXISTS read_at"
    )
