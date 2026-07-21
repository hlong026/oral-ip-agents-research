"""persist complete publish export packages

Revision ID: f9d0e1f2a3b4
Revises: f8c9d0e1f2a3
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f9d0e1f2a3b4"
down_revision: str | None = "f8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.add_column(sa.Column("export_key", sa.String(256), server_default="", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.drop_column("export_key")
