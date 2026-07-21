"""bind async asset jobs to credit reservations

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-21
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2b3c4d5e6f7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("voices", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reservation_id", sa.String(32), nullable=False, server_default=""))
    op.create_index("ix_voices_reservation_id", "voices", ["reservation_id"])

    with op.batch_alter_table("avatars", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reservation_id", sa.String(32), nullable=False, server_default=""))
    op.create_index("ix_avatars_reservation_id", "avatars", ["reservation_id"])


def downgrade() -> None:
    op.drop_index("ix_avatars_reservation_id", table_name="avatars")
    with op.batch_alter_table("avatars", schema=None) as batch_op:
        batch_op.drop_column("reservation_id")

    op.drop_index("ix_voices_reservation_id", table_name="voices")
    with op.batch_alter_table("voices", schema=None) as batch_op:
        batch_op.drop_column("reservation_id")
