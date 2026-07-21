"""add IM gray rollout accounts and monitoring events

Revision ID: a07b8c9d0e1f
Revises: ff6a7b8c9d0e
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a07b8c9d0e1f"
down_revision: str | None = "ff6a7b8c9d0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "im_gray_accounts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("approved_by", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_index("ix_im_gray_accounts_account_id", "im_gray_accounts", ["account_id"])
    op.create_index("ix_im_gray_accounts_user_id", "im_gray_accounts", ["user_id"])
    op.create_index("ix_im_gray_accounts_approved_by", "im_gray_accounts", ["approved_by"])

    op.create_table(
        "im_metric_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("account_id", sa.String(length=32), server_default="", nullable=False),
        sa.Column("user_id", sa.String(length=32), server_default="", nullable=False),
        sa.Column("detail", sa.String(length=256), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_im_metric_events_kind", "im_metric_events", ["kind"])
    op.create_index("ix_im_metric_events_account_id", "im_metric_events", ["account_id"])
    op.create_index("ix_im_metric_events_user_id", "im_metric_events", ["user_id"])
    op.create_index("ix_im_metric_events_created_at", "im_metric_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_im_metric_events_created_at", table_name="im_metric_events")
    op.drop_index("ix_im_metric_events_user_id", table_name="im_metric_events")
    op.drop_index("ix_im_metric_events_account_id", table_name="im_metric_events")
    op.drop_index("ix_im_metric_events_kind", table_name="im_metric_events")
    op.drop_table("im_metric_events")
    op.drop_index("ix_im_gray_accounts_approved_by", table_name="im_gray_accounts")
    op.drop_index("ix_im_gray_accounts_user_id", table_name="im_gray_accounts")
    op.drop_index("ix_im_gray_accounts_account_id", table_name="im_gray_accounts")
    op.drop_table("im_gray_accounts")
