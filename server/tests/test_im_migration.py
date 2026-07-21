"""私信远端消息键迁移必须可升级、回滚并再次升级。"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    path = Path(__file__).parents[1] / "alembic/versions/f0a1b2c3d4e5_im_remote_message_keys.py"
    spec = importlib.util.spec_from_file_location("im_remote_message_keys", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_im_remote_message_key_migration_round_trip() -> None:
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table(
        "im_messages",
        metadata,
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("conversation_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(4), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
    )
    metadata.create_all(engine)
    migration = _load_migration()

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        inspector = sa.inspect(connection)
        columns = {column["name"] for column in inspector.get_columns("im_messages")}
        constraints = {item["name"] for item in inspector.get_unique_constraints("im_messages")}
        assert {"remote_message_id", "remote_index"} <= columns
        assert {"uq_im_message_remote_id", "uq_im_message_remote_index"} <= constraints

        with Operations.context(context):
            migration.downgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("im_messages")}
        assert "remote_message_id" not in columns
        assert "remote_index" not in columns

        with Operations.context(context):
            migration.upgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("im_messages")}
        assert {"remote_message_id", "remote_index"} <= columns
