"""persist queue message ids

Revision ID: f8c9d0e1f2a3
Revises: f7b8c9d0e1f2
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8c9d0e1f2a3"
down_revision: str | None = "f7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("pipeline_tasks", "publish_jobs"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("queue_message_id", sa.String(64), server_default="", nullable=False))
            batch_op.create_index(f"ix_{table}_queue_message_id", ["queue_message_id"])


def downgrade() -> None:
    for table in ("publish_jobs", "pipeline_tasks"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_index(f"ix_{table}_queue_message_id")
            batch_op.drop_column("queue_message_id")
