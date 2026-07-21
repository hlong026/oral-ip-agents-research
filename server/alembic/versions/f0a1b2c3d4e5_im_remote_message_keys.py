"""add stable remote keys for IM history reconciliation

Revision ID: f0a1b2c3d4e5
Revises: d4e5f6a7b8c9, e1f2a3b4c5d6
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: tuple[str, str] = ("d4e5f6a7b8c9", "e1f2a3b4c5d6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.add_column(sa.Column("remote_message_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("remote_index", sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_im_message_remote_id",
            ["conversation_id", "remote_message_id"],
        )
        batch_op.create_unique_constraint(
            "uq_im_message_remote_index",
            ["conversation_id", "direction", "remote_index"],
        )


def downgrade() -> None:
    with op.batch_alter_table("im_messages") as batch_op:
        batch_op.drop_constraint("uq_im_message_remote_index", type_="unique")
        batch_op.drop_constraint("uq_im_message_remote_id", type_="unique")
        batch_op.drop_column("remote_index")
        batch_op.drop_column("remote_message_id")
