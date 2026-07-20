"""Alembic 环境（异步引擎；URL 由 app 配置注入，契约同源）"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.core.config import get_settings  # noqa: E402
from app.core.db import Base  # noqa: E402

# 触发全部模块 models 注册（与 app.core.db.init_models 保持一致）
from app.modules.auth import models as _auth  # noqa: E402,F401
from app.modules.avatar import models as _avatar  # noqa: E402,F401
from app.modules.billing import models as _billing  # noqa: E402,F401
from app.modules.content import models as _content  # noqa: E402,F401
from app.modules.ipasset import models as _ipasset  # noqa: E402,F401
from app.modules.notify import models as _notify  # noqa: E402,F401
from app.modules.pipeline import models as _pipeline  # noqa: E402,F401
from app.modules.im import models as _im  # noqa: E402,F401
from app.modules.publish import models as _publish  # noqa: E402,F401
from app.modules.voice import models as _voice  # noqa: E402,F401

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_settings().database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # sqlite ALTER 受限，batch 模式兼容
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
