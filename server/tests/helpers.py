"""测试辅助：激活码建码与登录（激活码即账号）"""

from datetime import UTC, datetime

from httpx import AsyncClient

from app.core.db import SessionLocal
from app.modules.activation import code_generator
from app.modules.activation.models import ActivationCode, ActivationRateLimit

DEFAULT_FINGERPRINT = "test-device-uuid.abcdef0123456789"


async def create_unused_code(
    *,
    plan_type: str = "trial",
    quota_amount: float = 200,
    duration_days: int = 30,
    expires_at: datetime | None = None,
) -> str:
    """直接建一张未使用的激活码（不走 SKU，使用码上冗余字段），返回明文码。"""
    raw = code_generator.generate_batch(1)[0]
    async with SessionLocal() as db:
        db.add(
            ActivationCode(
                code=code_generator.hash_code(raw),
                plan_type=plan_type,
                quota_amount=quota_amount,
                duration_days=duration_days,
                expires_at=expires_at,
            )
        )
        await db.commit()
    return raw


async def bind_used_code(user_id: str) -> str:
    """为已存在用户补一张已使用码（重复登录/绑定场景），返回明文码。"""
    raw = code_generator.generate_batch(1)[0]
    async with SessionLocal() as db:
        db.add(
            ActivationCode(
                code=code_generator.hash_code(raw),
                plan_type="trial",
                quota_amount=0,
                duration_days=30,
                status="used",
                bound_user_id=user_id,
                activated_at=datetime.now(UTC),
            )
        )
        await db.commit()
    return raw


async def code_login(
    client: AsyncClient,
    code: str,
    fingerprint: str = DEFAULT_FINGERPRINT,
) -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"code": code, "deviceFingerprint": fingerprint},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def reset_rate_limits() -> None:
    """清空频控记录（失败用例后调用，避免 IP 维度累计干扰其他测试）。"""
    from sqlalchemy import delete

    async with SessionLocal() as db:
        await db.execute(delete(ActivationRateLimit))
        await db.commit()
