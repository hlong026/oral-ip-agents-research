"""activation code login: users.phone/password_hash nullable + fingerprint widen

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 激活码用户不再持有手机号/密码；两列改为可空（PG 唯一索引天然允许多 NULL）
    op.alter_column("users", "phone", existing_type=sa.String(20), nullable=True)
    op.alter_column("users", "password_hash", existing_type=sa.String(128), nullable=True)
    # 组合软指纹（uuid.featureHash）超过原 64 位上限
    op.alter_column("users", "device_fingerprint", existing_type=sa.String(64), type_=sa.String(128))
    # 历史占位指纹 "web" 视为未绑定，首次码登录时重新绑定真实指纹
    op.execute("UPDATE users SET device_fingerprint = '' WHERE device_fingerprint = 'web'")


def downgrade() -> None:
    op.alter_column("users", "device_fingerprint", existing_type=sa.String(128), type_=sa.String(64))
    op.alter_column("users", "password_hash", existing_type=sa.String(128), nullable=False)
    op.alter_column("users", "phone", existing_type=sa.String(20), nullable=False)
