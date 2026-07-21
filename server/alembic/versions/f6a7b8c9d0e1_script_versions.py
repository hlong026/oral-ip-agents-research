"""persist traceable script versions

Revision ID: f6a7b8c9d0e1
Revises: f5e6f7a8b9c0
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "f5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scripts") as batch_op:
        batch_op.add_column(sa.Column("current_version", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("model_name", sa.String(64), server_default="", nullable=False))
        batch_op.add_column(sa.Column("prompt_version", sa.String(32), server_default="", nullable=False))

    op.create_table(
        "script_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("script_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(64), server_default="", nullable=False),
        sa.Column("prompt_version", sa.String(32), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("script_id", "version", name="uq_script_versions_script_version"),
    )
    op.create_index("ix_script_versions_script_id", "script_versions", ["script_id"])
    op.create_index("ix_script_versions_user_id", "script_versions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_script_versions_user_id", table_name="script_versions")
    op.drop_index("ix_script_versions_script_id", table_name="script_versions")
    op.drop_table("script_versions")
    with op.batch_alter_table("scripts") as batch_op:
        batch_op.drop_column("prompt_version")
        batch_op.drop_column("model_name")
        batch_op.drop_column("current_version")
