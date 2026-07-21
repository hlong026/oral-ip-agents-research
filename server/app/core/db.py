"""数据库会话（SQLAlchemy 2 async）+ Alembic 基线 Base"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """开发模式自动建表（生产走 Alembic 迁移）"""
    # 触发各模块 models 注册
    from app.modules.activation import models as _activation  # noqa: F401
    from app.modules.auth import models as _auth  # noqa: F401
    from app.modules.avatar import models as _avatar  # noqa: F401
    from app.modules.billing import models as _billing  # noqa: F401
    from app.modules.content import models as _content  # noqa: F401
    from app.modules.ipasset import models as _ipasset  # noqa: F401
    from app.modules.notify import models as _notify  # noqa: F401
    from app.modules.pipeline import models as _pipeline  # noqa: F401
    from app.modules.im import models as _im  # noqa: F401
    from app.modules.publish import models as _publish  # noqa: F401
    from app.modules.settings import models as _settings  # noqa: F401
    from app.modules.voice import models as _voice  # noqa: F401
    from app.core.audit import AuditLog as _audit  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
