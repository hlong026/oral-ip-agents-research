"""publish_jobs post_id_source（post_id 语义澄清：internal=内部追踪号 | platform=平台作品 ID）

Revision ID: a8b9c0d1e2f3
Revises: d2e3f4a5b6c7
Create Date: 2026-07-26 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("publish_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("post_id_source", sa.String(length=16), nullable=False, server_default=""))
    # 存量成功任务的 post_id 均为 SAU 哈希生成的内部追踪号
    op.execute("UPDATE publish_jobs SET post_id_source = 'internal' WHERE post_id != ''")


def downgrade() -> None:
    with op.batch_alter_table("publish_jobs", schema=None) as batch_op:
        batch_op.drop_column("post_id_source")
