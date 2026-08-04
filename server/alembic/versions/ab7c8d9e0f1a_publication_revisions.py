"""publication revisions

Revision ID: ab7c8d9e0f1a
Revises: dd5e6f7a8b9c
Create Date: 2026-07-29 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ab7c8d9e0f1a"
down_revision: str | None = "dd5e6f7a8b9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publication_revisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("base_render_version_id", sa.String(length=32), nullable=False),
        sa.Column("render_version_id", sa.String(length=32), nullable=False),
        sa.Column("content_spec_json", sa.Text(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "revision", name="uq_publication_revision_task_revision"),
    )
    op.create_index(op.f("ix_publication_revisions_user_id"), "publication_revisions", ["user_id"], unique=False)
    op.create_index(op.f("ix_publication_revisions_task_id"), "publication_revisions", ["task_id"], unique=False)
    op.create_index(op.f("ix_publication_revisions_status"), "publication_revisions", ["status"], unique=False)
    op.create_index(
        op.f("ix_publication_revisions_base_render_version_id"),
        "publication_revisions",
        ["base_render_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_publication_revisions_render_version_id"),
        "publication_revisions",
        ["render_version_id"],
        unique=False,
    )
    op.add_column(
        "publish_jobs",
        sa.Column("publication_revision_id", sa.String(length=32), nullable=False, server_default=""),
    )
    op.create_index(op.f("ix_publish_jobs_publication_revision_id"), "publish_jobs", ["publication_revision_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_publish_jobs_publication_revision_id"), table_name="publish_jobs")
    op.drop_column("publish_jobs", "publication_revision_id")
    op.drop_index(op.f("ix_publication_revisions_render_version_id"), table_name="publication_revisions")
    op.drop_index(op.f("ix_publication_revisions_base_render_version_id"), table_name="publication_revisions")
    op.drop_index(op.f("ix_publication_revisions_status"), table_name="publication_revisions")
    op.drop_index(op.f("ix_publication_revisions_task_id"), table_name="publication_revisions")
    op.drop_index(op.f("ix_publication_revisions_user_id"), table_name="publication_revisions")
    op.drop_table("publication_revisions")
