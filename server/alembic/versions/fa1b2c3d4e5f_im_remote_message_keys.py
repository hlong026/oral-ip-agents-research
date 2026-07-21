"""enforce IM remote message idempotency

Revision ID: fa1b2c3d4e5f
Revises: f9d0e1f2a3b4
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fa1b2c3d4e5f"
down_revision: str | None = "f9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.add_column(sa.Column("remote_message_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("remote_index", sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_im_messages_remote_message",
            ["conversation_id", "remote_message_id"],
        )
        batch_op.create_unique_constraint(
            "uq_im_messages_remote_index",
            ["conversation_id", "direction", "remote_index"],
        )


def downgrade() -> None:
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.drop_constraint("uq_im_messages_remote_index", type_="unique")
        batch_op.drop_constraint("uq_im_messages_remote_message", type_="unique")
        batch_op.drop_column("remote_index")
        batch_op.drop_column("remote_message_id")
