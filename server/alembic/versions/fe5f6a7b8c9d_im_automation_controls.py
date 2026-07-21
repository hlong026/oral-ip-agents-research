"""require IM automation consent and global kill switch

Revision ID: fe5f6a7b8c9d
Revises: fd4e5f6a7b8c
Create Date: 2026-07-21
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "fe5f6a7b8c9d"
down_revision: str | None = "fd4e5f6a7b8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "im_automation_consents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("risk_version", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auto_reply_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_index("ix_im_automation_consents_account_id", "im_automation_consents", ["account_id"])
    op.create_index("ix_im_automation_consents_user_id", "im_automation_consents", ["user_id"])
    op.create_table(
        "im_global_controls",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("stopped", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "im_global_controls",
            sa.column("id", sa.String),
            sa.column("stopped", sa.Boolean),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [{"id": "global", "stopped": True, "updated_at": datetime.now(UTC)}],
    )


def downgrade() -> None:
    op.drop_table("im_global_controls")
    op.drop_index("ix_im_automation_consents_user_id", table_name="im_automation_consents")
    op.drop_index("ix_im_automation_consents_account_id", table_name="im_automation_consents")
    op.drop_table("im_automation_consents")
