"""user_devices / device_bind_requests 建表 + 存量 users.device_fingerprint 搬迁（硬件机器码多设备绑定）

Revision ID: dd5e6f7a8b9c
Revises: cc4d5e6f7a8b
Create Date: 2026-07-27
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "dd5e6f7a8b9c"
down_revision: str | None = "cc4d5e6f7a8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_devices",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("device_key", sa.String(64), nullable=False),
        sa.Column("device_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False, server_default="web"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_devices_user_id", "user_devices", ["user_id"])
    op.create_index("uq_user_devices_user_key", "user_devices", ["user_id", "device_key"], unique=True)

    op.create_table(
        "device_bind_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("device_key", sa.String(64), nullable=False),
        sa.Column("device_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(32), nullable=False, server_default=""),
    )
    op.create_index("ix_device_bind_requests_user_id", "device_bind_requests", ["user_id"])
    op.create_index("ix_device_bind_requests_status", "device_bind_requests", ["status"])
    op.create_index(
        "uq_device_bind_requests_pending",
        "device_bind_requests",
        ["user_id", "device_key"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )

    # 存量搬迁：users.device_fingerprint 非空值搬入 user_devices
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, device_fingerprint FROM users WHERE device_fingerprint <> ''")).fetchall()
    now = datetime.now(UTC)
    for user_id, fingerprint in rows:
        device_key = fingerprint.partition(".")[0]
        source = "desktop-hw" if device_key.startswith("hw-") else "web"
        conn.execute(
            sa.text(
                "INSERT INTO user_devices (id, user_id, fingerprint, device_key, device_name, source,"
                " created_at, last_seen_at) VALUES (:id, :uid, :fp, :key, :name, :src, :ts, :ts)"
            ),
            {
                "id": uuid.uuid4().hex,
                "uid": user_id,
                "fp": fingerprint,
                "key": device_key[:64],
                "name": "历史绑定设备",
                "src": source,
                "ts": now,
            },
        )


def downgrade() -> None:
    op.drop_index("uq_device_bind_requests_pending", table_name="device_bind_requests")
    op.drop_index("ix_device_bind_requests_status", table_name="device_bind_requests")
    op.drop_index("ix_device_bind_requests_user_id", table_name="device_bind_requests")
    op.drop_table("device_bind_requests")
    op.drop_index("uq_user_devices_user_key", table_name="user_devices")
    op.drop_index("ix_user_devices_user_id", table_name="user_devices")
    op.drop_table("user_devices")
