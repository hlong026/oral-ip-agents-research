"""add_activation_tables

Revision ID: e1f2a3b4c5d6
Revises: 3c9752a6f9eb
Create Date: 2026-07-20 23:10:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: str | None = '3c9752a6f9eb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 激活码表
    op.create_table(
        'activation_codes',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('code', sa.String(32), unique=True, nullable=False),
        sa.Column('plan_type', sa.String(16), server_default='monthly', nullable=False),
        sa.Column('quota_amount', sa.Float, server_default='0', nullable=False),
        sa.Column('duration_days', sa.Integer, server_default='30', nullable=False),
        sa.Column('status', sa.String(16), server_default='unused', nullable=False),
        sa.Column('batch_id', sa.String(32), server_default='', nullable=False),
        sa.Column('channel', sa.String(32), server_default='', nullable=False),
        sa.Column('bound_user_id', sa.String(32), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_activation_codes_code', 'activation_codes', ['code'], unique=True)
    op.create_index('ix_activation_codes_status', 'activation_codes', ['status'])
    op.create_index('ix_activation_codes_batch_id', 'activation_codes', ['batch_id'])

    # 批次表
    op.create_table(
        'activation_batches',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('name', sa.String(64), server_default='', nullable=False),
        sa.Column('plan_type', sa.String(16), server_default='monthly', nullable=False),
        sa.Column('quota_amount', sa.Float, server_default='0', nullable=False),
        sa.Column('duration_days', sa.Integer, server_default='30', nullable=False),
        sa.Column('total_count', sa.Integer, server_default='0', nullable=False),
        sa.Column('used_count', sa.Integer, server_default='0', nullable=False),
        sa.Column('channel', sa.String(32), server_default='', nullable=False),
        sa.Column('code_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(32), server_default='', nullable=False),
    )

    # 用户订阅记录表
    op.create_table(
        'user_subscriptions',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_id', sa.String(32), nullable=False),
        sa.Column('code_id', sa.String(32), nullable=False),
        sa.Column('plan_type', sa.String(16), nullable=False),
        sa.Column('quota_granted', sa.Float, server_default='0', nullable=False),
        sa.Column('duration_days', sa.Integer, server_default='0', nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_user_subscriptions_user_id', 'user_subscriptions', ['user_id'])

    # users 表扩展字段
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('plan_type', sa.String(16), server_default='none', nullable=False))
        batch_op.add_column(sa.Column('plan_expires_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('device_fingerprint', sa.String(64), server_default='web', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('device_fingerprint')
        batch_op.drop_column('plan_expires_at')
        batch_op.drop_column('plan_type')
        batch_op.drop_column('activated_at')

    op.drop_table('user_subscriptions')
    op.drop_table('activation_batches')
    op.drop_table('activation_codes')
