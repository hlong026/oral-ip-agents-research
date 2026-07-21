"""default IM replies to suggestions and persist moderation

Revision ID: fd4e5f6a7b8c
Revises: fc3d4e5f6a7b
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fd4e5f6a7b8c"
down_revision: str | None = "fc3d4e5f6a7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("im_auto_reply_rules") as batch_op:
        batch_op.add_column(
            sa.Column("delivery_mode", sa.String(length=16), server_default="suggestion", nullable=False)
        )
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.add_column(
            sa.Column("moderation_status", sa.String(length=16), server_default="approved", nullable=False)
        )
        batch_op.add_column(sa.Column("moderation_reason", sa.String(length=256), server_default="", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.drop_column("moderation_reason")
        batch_op.drop_column("moderation_status")
    with op.batch_alter_table("im_auto_reply_rules") as batch_op:
        batch_op.drop_column("delivery_mode")
