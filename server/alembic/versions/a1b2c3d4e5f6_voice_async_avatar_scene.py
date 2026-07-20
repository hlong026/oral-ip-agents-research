"""voice async clone + avatar multi-scene

Revision ID: a1b2c3d4e5f6
Revises: fed35a9ee146
Create Date: 2026-07-19 22:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = 'fed35a9ee146'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # voices 表新增字段
    with op.batch_alter_table('voices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('provider_task_id', sa.String(length=64), server_default='', nullable=False))
        batch_op.add_column(sa.Column('language', sa.String(length=16), server_default='zh', nullable=False))
        batch_op.add_column(sa.Column('demo_key', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('rate', sa.String(length=8), server_default='1.0', nullable=False))
        batch_op.add_column(sa.Column('volume', sa.String(length=8), server_default='1.0', nullable=False))
        batch_op.add_column(sa.Column('pitch', sa.String(length=8), server_default='1.0', nullable=False))
        batch_op.alter_column('status', type_=sa.String(length=20), existing_type=sa.String(length=16))

    # avatars 表新增字段
    with op.batch_alter_table('avatars', schema=None) as batch_op:
        batch_op.add_column(sa.Column('provider_task_id', sa.String(length=64), server_default='', nullable=False))
        batch_op.add_column(sa.Column('avatar_type', sa.String(length=16), server_default='video', nullable=False))
        batch_op.add_column(sa.Column('scene', sa.String(length=32), server_default='', nullable=False))
        batch_op.alter_column('status', type_=sa.String(length=20), existing_type=sa.String(length=16))


def downgrade() -> None:
    with op.batch_alter_table('voices', schema=None) as batch_op:
        batch_op.drop_column('provider_task_id')
        batch_op.drop_column('language')
        batch_op.drop_column('demo_key')
        batch_op.drop_column('rate')
        batch_op.drop_column('volume')
        batch_op.drop_column('pitch')
        batch_op.alter_column('status', type_=sa.String(length=16), existing_type=sa.String(length=20))

    with op.batch_alter_table('avatars', schema=None) as batch_op:
        batch_op.drop_column('provider_task_id')
        batch_op.drop_column('avatar_type')
        batch_op.drop_column('scene')
        batch_op.alter_column('status', type_=sa.String(length=16), existing_type=sa.String(length=20))
