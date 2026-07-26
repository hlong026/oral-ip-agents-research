"""add persistent async content jobs

Revision ID: c1d2e3f4a5b6
Revises: b18c9d0e1f2a
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b18c9d0e1f2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stage", sa.String(128), server_default="等待处理", nullable=False),
        sa.Column("payload_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("result_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("reservation_id", sa.String(32), server_default="", nullable=False),
        sa.Column("queue_message_id", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_content_jobs_user_id", "content_jobs", ["user_id"])
    op.create_index("ix_content_jobs_kind", "content_jobs", ["kind"])
    op.create_index("ix_content_jobs_status", "content_jobs", ["status"])
    op.create_index("ix_content_jobs_reservation_id", "content_jobs", ["reservation_id"])
    op.create_index("ix_content_jobs_queue_message_id", "content_jobs", ["queue_message_id"])


def downgrade() -> None:
    op.drop_index("ix_content_jobs_queue_message_id", table_name="content_jobs")
    op.drop_index("ix_content_jobs_reservation_id", table_name="content_jobs")
    op.drop_index("ix_content_jobs_status", table_name="content_jobs")
    op.drop_index("ix_content_jobs_kind", table_name="content_jobs")
    op.drop_index("ix_content_jobs_user_id", table_name="content_jobs")
    op.drop_table("content_jobs")
