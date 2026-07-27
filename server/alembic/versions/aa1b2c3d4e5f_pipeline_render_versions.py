"""add durable pipeline render versions

Revision ID: aa1b2c3d4e5f
Revises: a9c0d1e2f3a4
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "aa1b2c3d4e5f"
down_revision: str | None = "a9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("pipeline_tasks") as batch_op:
        batch_op.add_column(sa.Column("script_id", sa.String(32), server_default="", nullable=False))
        batch_op.add_column(sa.Column("script_version", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("active_render_version", sa.Integer(), server_default="0", nullable=False))
        batch_op.create_index("ix_pipeline_tasks_script_id", ["script_id"])

    op.create_table(
        "pipeline_render_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("base_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("config_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("reservation_id", sa.String(32), server_default="", nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("video_key", sa.String(256), server_default="", nullable=False),
        sa.Column("cover_key", sa.String(256), server_default="", nullable=False),
        sa.Column("quality_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("queue_message_id", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "version", name="uq_pipeline_render_task_version"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_pipeline_render_user_idempotency"),
    )
    op.create_index("ix_pipeline_render_versions_task_id", "pipeline_render_versions", ["task_id"])
    op.create_index("ix_pipeline_render_versions_user_id", "pipeline_render_versions", ["user_id"])
    op.create_index("ix_pipeline_render_versions_status", "pipeline_render_versions", ["status"])
    op.create_index("ix_pipeline_render_versions_reservation_id", "pipeline_render_versions", ["reservation_id"])
    op.create_index("ix_pipeline_render_versions_is_active", "pipeline_render_versions", ["is_active"])
    op.create_index("ix_pipeline_render_versions_queue_message_id", "pipeline_render_versions", ["queue_message_id"])

    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.add_column(sa.Column("render_version_id", sa.String(32), server_default="", nullable=False))
        batch_op.add_column(sa.Column("render_version", sa.Integer(), server_default="0", nullable=False))
        batch_op.create_index("ix_publish_jobs_render_version_id", ["render_version_id"])
    op.create_index(
        "uq_publish_jobs_render_platform",
        "publish_jobs",
        ["user_id", "task_id", "render_version_id", "platform"],
        unique=True,
        postgresql_where=sa.text("render_version_id <> ''"),
        sqlite_where=sa.text("render_version_id <> ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_publish_jobs_render_platform", table_name="publish_jobs")
    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.drop_index("ix_publish_jobs_render_version_id")
        batch_op.drop_column("render_version")
        batch_op.drop_column("render_version_id")

    op.drop_index("ix_pipeline_render_versions_queue_message_id", table_name="pipeline_render_versions")
    op.drop_index("ix_pipeline_render_versions_is_active", table_name="pipeline_render_versions")
    op.drop_index("ix_pipeline_render_versions_reservation_id", table_name="pipeline_render_versions")
    op.drop_index("ix_pipeline_render_versions_status", table_name="pipeline_render_versions")
    op.drop_index("ix_pipeline_render_versions_user_id", table_name="pipeline_render_versions")
    op.drop_index("ix_pipeline_render_versions_task_id", table_name="pipeline_render_versions")
    op.drop_table("pipeline_render_versions")

    with op.batch_alter_table("pipeline_tasks") as batch_op:
        batch_op.drop_index("ix_pipeline_tasks_script_id")
        batch_op.drop_column("active_render_version")
        batch_op.drop_column("script_version")
        batch_op.drop_column("script_id")
