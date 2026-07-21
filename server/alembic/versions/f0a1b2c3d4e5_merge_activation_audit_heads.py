"""merge activation and audit heads

Revision ID: f0a1b2c3d4e5
Revises: d4e5f6a7b8c9, e1f2a3b4c5d6
Create Date: 2026-07-21
"""

from collections.abc import Sequence

revision: str = "f0a1b2c3d4e5"
down_revision: str | tuple[str, str] | None = ("d4e5f6a7b8c9", "e1f2a3b4c5d6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
