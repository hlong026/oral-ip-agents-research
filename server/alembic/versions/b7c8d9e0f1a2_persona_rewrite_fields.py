"""persona 三阶段仿写引擎扩展字段

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-19
"""

import sqlalchemy as sa

from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("personas", schema=None) as batch_op:
        batch_op.add_column(sa.Column("audience", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("content_pillars", sa.Text(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("style_samples", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("catchphrase", sa.String(256), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("video_duration", sa.Integer(), nullable=False, server_default="60"))
        batch_op.add_column(sa.Column("cta_style", sa.String(128), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("avoid_topics", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("personas", schema=None) as batch_op:
        batch_op.drop_column("avoid_topics")
        batch_op.drop_column("cta_style")
        batch_op.drop_column("video_duration")
        batch_op.drop_column("catchphrase")
        batch_op.drop_column("style_samples")
        batch_op.drop_column("content_pillars")
        batch_op.drop_column("audience")
