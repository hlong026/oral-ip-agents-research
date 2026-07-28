"""make voices.provider_voice_id unique (cloud recovery concurrent import guard)

Revision ID: cc4d5e6f7a8b
Revises: bb2c3d4e5f6a
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cc4d5e6f7a8b"
down_revision: str | None = "bb2c3d4e5f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_voices_provider_voice_id",
        "voices",
        ["provider_voice_id"],
        unique=True,
        sqlite_where=sa.text("provider_voice_id <> ''"),
        postgresql_where=sa.text("provider_voice_id <> ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_voices_provider_voice_id", table_name="voices")
