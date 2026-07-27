"""expand status columns for reconciliation workflow

Revision ID: a9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9c0d1e2f3a4"
down_revision: str | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table, old_length in (("pipeline_tasks", 16), ("voices", 20), ("avatars", 20)):
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.String(old_length),
                type_=sa.String(32),
                existing_nullable=False,
            )


def downgrade() -> None:
    connection = op.get_bind()
    for table, old_length in (("pipeline_tasks", 16), ("voices", 20), ("avatars", 20)):
        oversized = connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE length(status) > :max_length"),
            {"max_length": old_length},
        ).scalar_one()
        if oversized:
            raise RuntimeError(f"cannot downgrade {table}.status while {oversized} rows exceed {old_length} characters")
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.String(32),
                type_=sa.String(old_length),
                existing_nullable=False,
            )
