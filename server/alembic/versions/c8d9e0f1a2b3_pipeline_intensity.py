"""pipeline_tasks 新增 intensity 字段

Revision ID: c8d9e0f1a2b3
Revises: 3c9752a6f9eb
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = "c8d9e0f1a2b3"
down_revision = "3c9752a6f9eb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pipeline_tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("intensity", sa.String(16), nullable=False, server_default="structure"))


def downgrade() -> None:
    with op.batch_alter_table("pipeline_tasks", schema=None) as batch_op:
        batch_op.drop_column("intensity")
