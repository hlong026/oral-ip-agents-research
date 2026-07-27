"""add durable webhook retry queue

Revision ID: bb2c3d4e5f6a
Revises: aa1b2c3d4e5f
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bb2c3d4e5f6a"
down_revision: str | None = "aa1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.add_column(sa.Column("payload_json", sa.Text(), server_default="{}", nullable=False))
        batch_op.add_column(sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("retry_count")
        batch_op.drop_column("payload_json")
