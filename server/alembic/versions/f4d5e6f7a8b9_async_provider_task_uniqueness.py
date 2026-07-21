"""make async provider task identifiers unique

Revision ID: f4d5e6f7a8b9
Revises: f3c4d5e6f7a8
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4d5e6f7a8b9"
down_revision: str | None = "f3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_voices_provider_task_id",
        "voices",
        ["provider_task_id"],
        unique=True,
        sqlite_where=sa.text("provider_task_id <> ''"),
        postgresql_where=sa.text("provider_task_id <> ''"),
    )
    op.create_index(
        "uq_avatars_provider_task_id",
        "avatars",
        ["provider_task_id"],
        unique=True,
        sqlite_where=sa.text("provider_task_id <> ''"),
        postgresql_where=sa.text("provider_task_id <> ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_avatars_provider_task_id", table_name="avatars")
    op.drop_index("uq_voices_provider_task_id", table_name="voices")
