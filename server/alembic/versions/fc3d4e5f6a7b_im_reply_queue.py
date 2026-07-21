"""persist delayed IM reply queue identity

Revision ID: fc3d4e5f6a7b
Revises: fb2c3d4e5f6a
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fc3d4e5f6a7b"
down_revision: str | None = "fb2c3d4e5f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.add_column(sa.Column("queue_message_id", sa.String(length=64), server_default="", nullable=False))
        batch_op.add_column(sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_im_messages_queue_message_id", ["queue_message_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.drop_index("ix_im_messages_queue_message_id")
        batch_op.drop_column("scheduled_at")
        batch_op.drop_column("queue_message_id")
