"""persist clone consent evidence

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("voices", "avatars"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("consent_hash", sa.String(64), server_default="", nullable=False))
            batch_op.add_column(sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for table in ("avatars", "voices"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("consented_at")
            batch_op.drop_column("consent_hash")
