"""persist truthful IM send state

Revision ID: fb2c3d4e5f6a
Revises: fa1b2c3d4e5f
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fb2c3d4e5f6a"
down_revision: str | None = "fa1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.add_column(sa.Column("send_status", sa.String(length=16), server_default="received", nullable=False))
        batch_op.add_column(sa.Column("send_error", sa.String(length=256), server_default="", nullable=False))
        batch_op.add_column(sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("manual_takeover", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.create_index("ix_im_messages_send_status", ["send_status"], unique=False)

    op.execute("UPDATE im_messages SET send_status = 'sent' WHERE direction = 'out'")


def downgrade() -> None:
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.drop_index("ix_im_messages_send_status")
        batch_op.drop_column("manual_takeover")
        batch_op.drop_column("retry_count")
        batch_op.drop_column("send_error")
        batch_op.drop_column("send_status")
