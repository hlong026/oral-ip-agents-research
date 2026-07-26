"""allow quota usage to store full billing module names

Revision ID: b18c9d0e1f2a
Revises: a07b8c9d0e1f
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b18c9d0e1f2a"
down_revision: str | None = "a07b8c9d0e1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("quota_usage") as batch_op:
        batch_op.alter_column(
            "step",
            existing_type=sa.String(16),
            type_=sa.String(32),
            existing_nullable=False,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE quota_usage "
            "SET step = 'rewrite' "
            "WHERE step = 'script_generation'"
        )
    )
    with op.batch_alter_table("quota_usage") as batch_op:
        batch_op.alter_column(
            "step",
            existing_type=sa.String(32),
            type_=sa.String(16),
            existing_nullable=False,
        )
