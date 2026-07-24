"""billing idempotent settlement, credit grant expiry, and ledger indexes

Revision ID: a1b2c3d4e5f7
Revises: ff6a7b8c9d0e
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | None = "a07b8c9d0e1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # P0: CreditReservation 新增 settled_by 字段，追踪结算发起方
    with op.batch_alter_table("credit_reservations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("settled_by", sa.String(64), nullable=False, server_default=""))
    op.create_index("ix_credit_reservations_settled_by", "credit_reservations", ["settled_by"])

    # P0: 结算流水幂等唯一索引（同一 reservation 只允许一条 settle 记录）
    op.create_index(
        "uq_ledger_settle_per_reservation",
        "credit_ledger",
        ["reference_id"],
        unique=True,
        postgresql_where=sa.text("event_type = 'settle'"),
        sqlite_where=sa.text("event_type = 'settle'"),
    )

    # P1: CreditGrant 新增 status / expired_at 字段支持过期清零
    with op.batch_alter_table("credit_grants", schema=None) as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(16), nullable=False, server_default="active"))
        batch_op.add_column(sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_credit_grants_status", "credit_grants", ["status"])

    # P2: CreditLedger 用户+时间复合索引，加速消费明细分页查询
    op.create_index(
        "ix_credit_ledger_user_created",
        "credit_ledger",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_credit_ledger_user_created", table_name="credit_ledger")

    op.drop_index("ix_credit_grants_status", table_name="credit_grants")
    with op.batch_alter_table("credit_grants", schema=None) as batch_op:
        batch_op.drop_column("expired_at")
        batch_op.drop_column("status")

    op.drop_index("uq_ledger_settle_per_reservation", table_name="credit_ledger")

    op.drop_index("ix_credit_reservations_settled_by", table_name="credit_reservations")
    with op.batch_alter_table("credit_reservations", schema=None) as batch_op:
        batch_op.drop_column("settled_by")
