"""add im tables

Revision ID: 3c9752a6f9eb
Revises: c9d0e1f2a3b4
Create Date: 2026-07-20 09:16:57.149067
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3c9752a6f9eb"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "im_conversations" not in tables:
        op.create_table(
            "im_conversations",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("platform", sa.String(16), nullable=False, server_default="douyin"),
            sa.Column("remote_uid", sa.String(64), nullable=False, server_default=""),
            sa.Column("remote_nickname", sa.String(64), nullable=False, server_default=""),
            sa.Column("remote_avatar", sa.String(256), nullable=False, server_default=""),
            sa.Column("dy_conversation_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("dy_conversation_short_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("dy_ticket", sa.String(128), nullable=False, server_default=""),
            sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_im_conversations_account_id", "im_conversations", ["account_id"])
        op.create_index("ix_im_conversations_user_id", "im_conversations", ["user_id"])

    if "im_messages" not in tables:
        op.create_table(
            "im_messages",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("conversation_id", sa.String(32), nullable=False),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("direction", sa.String(4), nullable=False, server_default="in"),
            sa.Column("msg_type", sa.Integer(), nullable=False, server_default="7"),
            sa.Column("content", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("auto_replied", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("rule_id", sa.String(32), nullable=False, server_default=""),
            sa.Column("reply_content", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_im_messages_conversation_id", "im_messages", ["conversation_id"])
        op.create_index("ix_im_messages_user_id", "im_messages", ["user_id"])
        op.create_index("ix_im_messages_rule_id", "im_messages", ["rule_id"])
    else:
        columns = {column["name"] for column in inspector.get_columns("im_messages")}
        if "rule_id" not in columns:
            with op.batch_alter_table("im_messages", schema=None) as batch_op:
                batch_op.add_column(sa.Column("rule_id", sa.String(32), server_default="", nullable=False))
                batch_op.create_index("ix_im_messages_rule_id", ["rule_id"], unique=False)

    if "im_auto_reply_rules" not in tables:
        op.create_table(
            "im_auto_reply_rules",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("account_id", sa.String(32), nullable=False, server_default=""),
            sa.Column("name", sa.String(64), nullable=False, server_default=""),
            sa.Column("trigger_type", sa.String(16), nullable=False, server_default="all"),
            sa.Column("trigger_pattern", sa.String(256), nullable=False, server_default=""),
            sa.Column("reply_mode", sa.String(16), nullable=False, server_default="template"),
            sa.Column("reply_template", sa.Text(), nullable=False, server_default=""),
            sa.Column("llm_prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="50"),
            sa.Column("delay_min", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("delay_max", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_im_auto_reply_rules_user_id", "im_auto_reply_rules", ["user_id"])

    if "im_listener_states" not in tables:
        op.create_table(
            "im_listener_states",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="disconnected"),
            sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_msg", sa.String(256), nullable=False, server_default=""),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_im_listener_states_account_id", "im_listener_states", ["account_id"], unique=True)
        op.create_index("ix_im_listener_states_user_id", "im_listener_states", ["user_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in ("im_listener_states", "im_auto_reply_rules", "im_messages", "im_conversations"):
        if table in tables:
            op.drop_table(table)
