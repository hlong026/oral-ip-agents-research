"""merge duplicate IM conversations and enforce remote identity

Revision ID: ff6a7b8c9d0e
Revises: fe5f6a7b8c9d
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ff6a7b8c9d0e"
down_revision: str | None = "fe5f6a7b8c9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    conversations = sa.table(
        "im_conversations",
        sa.column("id", sa.String),
        sa.column("account_id", sa.String),
        sa.column("user_id", sa.String),
        sa.column("remote_uid", sa.String),
        sa.column("unread_count", sa.Integer),
        sa.column("last_message_at", sa.DateTime(timezone=True)),
    )
    messages = sa.table(
        "im_messages",
        sa.column("id", sa.String),
        sa.column("conversation_id", sa.String),
        sa.column("direction", sa.String),
        sa.column("remote_message_id", sa.String),
        sa.column("remote_index", sa.Integer),
    )
    duplicate_keys = connection.execute(
        sa.select(
            conversations.c.account_id,
            conversations.c.user_id,
            conversations.c.remote_uid,
        )
        .where(conversations.c.remote_uid != "")
        .group_by(
            conversations.c.account_id,
            conversations.c.user_id,
            conversations.c.remote_uid,
        )
        .having(sa.func.count(conversations.c.id) > 1)
    ).all()
    for account_id, user_id, remote_uid in duplicate_keys:
        rows = connection.execute(
            sa.select(
                conversations.c.id,
                conversations.c.unread_count,
            )
            .where(
                conversations.c.account_id == account_id,
                conversations.c.user_id == user_id,
                conversations.c.remote_uid == remote_uid,
            )
            .order_by(conversations.c.last_message_at.desc(), conversations.c.id.asc())
        ).all()
        keeper_id = rows[0].id
        duplicate_ids = [row.id for row in rows[1:]]
        for duplicate_id in duplicate_ids:
            keeper_messages = messages.alias("keeper_messages")
            connection.execute(
                messages.delete().where(
                    messages.c.conversation_id == duplicate_id,
                    sa.or_(
                        sa.and_(
                            messages.c.remote_message_id.is_not(None),
                            sa.exists(
                                sa.select(keeper_messages.c.id).where(
                                    keeper_messages.c.conversation_id == keeper_id,
                                    keeper_messages.c.remote_message_id == messages.c.remote_message_id,
                                )
                            ),
                        ),
                        sa.and_(
                            messages.c.remote_index.is_not(None),
                            sa.exists(
                                sa.select(keeper_messages.c.id).where(
                                    keeper_messages.c.conversation_id == keeper_id,
                                    keeper_messages.c.direction == messages.c.direction,
                                    keeper_messages.c.remote_index == messages.c.remote_index,
                                )
                            ),
                        ),
                    ),
                )
            )
            connection.execute(
                messages.update()
                .where(messages.c.conversation_id == duplicate_id)
                .values(conversation_id=keeper_id)
            )
        connection.execute(
            conversations.update()
            .where(conversations.c.id == keeper_id)
            .values(unread_count=sum(int(row.unread_count or 0) for row in rows))
        )
        connection.execute(conversations.delete().where(conversations.c.id.in_(duplicate_ids)))

    op.create_index(
        "uq_im_conversations_owner_remote",
        "im_conversations",
        ["account_id", "user_id", "remote_uid"],
        unique=True,
        postgresql_where=sa.text("remote_uid <> ''"),
        sqlite_where=sa.text("remote_uid <> ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_im_conversations_owner_remote", table_name="im_conversations")
