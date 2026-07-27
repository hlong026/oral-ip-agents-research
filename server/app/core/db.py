"""数据库会话（SQLAlchemy 2 async）+ Alembic 基线 Base"""

from collections.abc import AsyncGenerator
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
SERVER_ROOT = Path(__file__).resolve().parents[2]
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """开发模式自动建表（生产走 Alembic 迁移）"""
    if settings.app_env not in {"dev", "test"}:
        return

    # 触发各模块 models 注册
    from app.core.audit import AuditLog as _audit  # noqa: F401
    from app.modules.activation import models as _activation  # noqa: F401
    from app.modules.auth import models as _auth  # noqa: F401
    from app.modules.avatar import models as _avatar  # noqa: F401
    from app.modules.billing import models as _billing  # noqa: F401
    from app.modules.catalog import models as _catalog  # noqa: F401
    from app.modules.content import models as _content  # noqa: F401
    from app.modules.im import models as _im  # noqa: F401
    from app.modules.ipasset import models as _ipasset  # noqa: F401
    from app.modules.notify import models as _notify  # noqa: F401
    from app.modules.pipeline import models as _pipeline  # noqa: F401
    from app.modules.publish import models as _publish  # noqa: F401
    from app.modules.settings import models as _settings  # noqa: F401
    from app.modules.voice import models as _voice  # noqa: F401
    from app.modules.webhook import models as _webhook  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def verify_migrations_current() -> None:
    """Fail production startup when the database is not at the Alembic head."""
    alembic_config = Config(str(SERVER_ROOT / "alembic.ini"))
    expected_heads = set(ScriptDirectory.from_config(alembic_config).get_heads())

    async with engine.connect() as conn:
        current_heads = set(
            await conn.run_sync(lambda sync_conn: MigrationContext.configure(sync_conn).get_current_heads())
        )

    if current_heads != expected_heads:
        raise RuntimeError(
            f"数据库迁移版本不一致：current={sorted(current_heads) or ['<none>']}, expected={sorted(expected_heads)}"
        )


async def database_ready() -> bool:
    """运行期数据库探针；只执行常量查询，不修改业务状态。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
