"""persist webhook event receipts

Revision ID: f5e6f7a8b9c0
Revises: f4d5e6f7a8b9
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5e6f7a8b9c0"
down_revision: str | None = "f4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("msg_type", sa.Integer(), nullable=False),
        sa.Column("provider_task_id", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="processing", nullable=False),
        sa.Column("error_context", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),
        sa.UniqueConstraint("provider", "msg_type", "provider_task_id", name="uq_webhook_provider_task"),
    )


def downgrade() -> None:
    op.drop_table("webhook_events")
