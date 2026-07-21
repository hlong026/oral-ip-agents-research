"""persist activation brute-force rate limits

Revision ID: f3c4d5e6f7a8
Revises: f2b3c4d5e6f7
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3c4d5e6f7a8"
down_revision: str | None = "f2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activation_rate_limits",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scope", "subject_hash", "action", name="uq_activation_rate_subject"),
    )
    op.create_index(
        "ix_activation_rate_limits_subject_hash",
        "activation_rate_limits",
        ["subject_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_activation_rate_limits_subject_hash", table_name="activation_rate_limits")
    op.drop_table("activation_rate_limits")
