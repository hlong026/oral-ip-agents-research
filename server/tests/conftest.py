"""pytest 环境：临时 sqlite + 临时媒体目录 + 进程内事件总线

必须在导入 app 之前设置环境变量（get_settings 为 lru_cache）。
所有 Provider 凭据留空 → 触发 StepRecoverableError → 自动降级到 Mock。
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="oral-test-")
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/test.db"
os.environ["LOCAL_STORAGE_DIR"] = os.path.join(_TMP, "storage")
os.environ["STORAGE_DRIVER"] = "local"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/9"  # 不可达 → 降级进程内广播
os.environ["APP_SECRET"] = "test-secret"
os.environ["CONFIG_ENCRYPTION_KEY"] = "test-config-encryption-key"
os.environ["IM_GRAY_MAX_ACCOUNTS"] = "1000"
# 确保所有 Provider 凭据为空 → 快速降级到 Mock
os.environ.setdefault("DEEPSEEK_API_KEY", "")
os.environ.setdefault("DOUYIDOU_APP_ID", "")
os.environ.setdefault("DASHSCOPE_API_KEY", "")
os.environ.setdefault("FEIYING_API_KEY", "")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app, lifespan  # noqa: E402


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
