"""激活码登录链路契约测试：开户 / 重复登录 / 设备绑定 / 到期拦截 / 解绑重绑 / 刷新指纹 / 指纹漂移。"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update

from app.core.db import SessionLocal
from app.core.security import decode_token, hash_password
from app.modules.activation.models import ActivationCode
from app.modules.auth.models import User
from tests.helpers import code_login, create_unused_code, reset_rate_limits


def _fp() -> str:
    return f"fp-{uuid.uuid4().hex[:12]}.abcd1234"


def _auth(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _user_id(tokens: dict) -> str:
    return str(decode_token(tokens["accessToken"])["sub"])


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    phone = f"139{uuid.uuid4().hex[:8]}"
    password = "Admin@12345"
    async with SessionLocal() as db:
        db.add(
            User(
                phone=phone,
                password_hash=hash_password(password),
                nickname="管理员",
                avatar_char="管",
                role="admin",
            )
        )
        await db.commit()
    r = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


async def test_first_code_login_creates_account_with_plan_and_binding(client: AsyncClient):
    code = await create_unused_code(quota_amount=200, duration_days=30)
    tokens = await code_login(client, code, fingerprint=_fp())

    me = await client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["nickname"].startswith("创作者")
    assert body["deviceBound"] is True
    assert body["planType"] == "trial"
    assert body["planExpiresAt"] is not None

    balance = await client.get("/api/v1/billing/balance", headers=_auth(tokens))
    assert balance.status_code == 200, balance.text
    assert balance.json()["balance"] == 200

    sub = await client.get("/api/v1/activation/subscription", headers=_auth(tokens))
    assert sub.status_code == 200, sub.text
    assert sub.json()["planType"] == "trial"


async def test_repeat_login_with_same_code_and_device_succeeds(client: AsyncClient):
    code = await create_unused_code()
    fp = _fp()
    first = await code_login(client, code, fingerprint=fp)
    second = await code_login(client, code, fingerprint=fp)

    assert _user_id(first) == _user_id(second)
    me = await client.get("/api/v1/auth/me", headers=_auth(second))
    assert me.status_code == 200, me.text


async def test_login_rejected_when_device_fingerprint_mismatches(client: AsyncClient):
    """新设备登录且超出绑定上限（默认 1）：403 DEVICE_LIMIT_REACHED，并自动落库 pending 申请。"""
    code = await create_unused_code()
    await code_login(client, code, fingerprint=_fp())

    r = await client.post(
        "/api/v1/auth/login",
        json={"code": code, "deviceFingerprint": _fp()},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "DEVICE_LIMIT_REACHED"
    await reset_rate_limits()


async def test_login_tolerates_feature_hash_drift_on_same_device(client: AsyncClient):
    """uuid 段一致、featureHash 漂移（浏览器升级等）：登录与刷新均不应被锁，并重绑最新指纹。"""
    code = await create_unused_code()
    device = f"fp-{uuid.uuid4().hex[:12]}"
    first = await code_login(client, code, fingerprint=f"{device}.hash-old")
    drifted = await code_login(client, code, fingerprint=f"{device}.hash-new")
    assert _user_id(first) == _user_id(drifted)

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": drifted["refreshToken"], "deviceFingerprint": f"{device}.hash-newer"},
    )
    assert refreshed.status_code == 200, refreshed.text


async def test_login_rejects_blank_or_short_fingerprint(client: AsyncClient):
    """空/过短指纹直接 422：禁止绕过设备绑定防线。"""
    code = await create_unused_code()
    for bad in ("", "short"):
        r = await client.post(
            "/api/v1/auth/login",
            json={"code": code, "deviceFingerprint": bad},
        )
        assert r.status_code == 422, r.text


async def test_expired_or_revoked_code_cannot_login(client: AsyncClient):
    expired = await create_unused_code(expires_at=datetime.now(UTC) - timedelta(days=1))
    r1 = await client.post(
        "/api/v1/auth/login",
        json={"code": expired, "deviceFingerprint": _fp()},
    )
    assert r1.status_code == 400, r1.text
    assert r1.json()["detail"]["code"] == "CODE_EXPIRED"

    revoked = await create_unused_code()
    from app.modules.activation import code_generator

    async with SessionLocal() as db:
        await db.execute(
            update(ActivationCode)
            .where(ActivationCode.code == code_generator.hash_code(revoked))
            .values(status="revoked")
        )
        await db.commit()
    r2 = await client.post(
        "/api/v1/auth/login",
        json={"code": revoked, "deviceFingerprint": _fp()},
    )
    assert r2.status_code == 400, r2.text
    assert r2.json()["detail"]["code"] == "CODE_UNAVAILABLE"
    await reset_rate_limits()


async def test_plan_expired_blocks_business_api_but_allows_renewal(client: AsyncClient):
    code = await create_unused_code(duration_days=30)
    tokens = await code_login(client, code, fingerprint=_fp())
    user_id = _user_id(tokens)

    async with SessionLocal() as db:
        await db.execute(
            update(User).where(User.id == user_id).values(plan_expires_at=datetime.now(UTC) - timedelta(days=1))
        )
        await db.commit()

    blocked = await client.get("/api/v1/billing/balance", headers=_auth(tokens))
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"]["code"] == "PLAN_EXPIRED"

    # 续费链路豁免：me / subscription / redeem 仍可访问
    me = await client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert me.status_code == 200, me.text

    renewal_code = await create_unused_code(quota_amount=100, duration_days=30)
    redeemed = await client.post(
        "/api/v1/activation/redeem",
        headers=_auth(tokens),
        json={"code": renewal_code},
    )
    assert redeemed.status_code == 200, redeemed.text

    recovered = await client.get("/api/v1/billing/balance", headers=_auth(tokens))
    assert recovered.status_code == 200, recovered.text


async def test_admin_unbind_allows_rebinding_on_new_device(client: AsyncClient):
    code = await create_unused_code()
    old_fp = _fp()
    tokens = await code_login(client, code, fingerprint=old_fp)
    user_id = _user_id(tokens)

    admin_headers = await _admin_headers(client)
    unbind = await client.post(f"/api/admin/v1/users/{user_id}/unbind-device", headers=admin_headers)
    assert unbind.status_code == 200, unbind.text

    # 解绑后旧 refresh 会话被吊销
    refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": tokens["refreshToken"], "deviceFingerprint": old_fp},
    )
    assert refresh.status_code == 401, refresh.text

    # 新设备重新绑定登录
    new_fp = _fp()
    rebound = await code_login(client, code, fingerprint=new_fp)
    me = await client.get("/api/v1/auth/me", headers=_auth(rebound))
    assert me.status_code == 200, me.text
    assert me.json()["deviceBound"] is True


async def test_refresh_requires_bound_device_fingerprint(client: AsyncClient):
    code = await create_unused_code()
    fp = _fp()
    tokens = await code_login(client, code, fingerprint=fp)

    stolen = await client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": tokens["refreshToken"], "deviceFingerprint": _fp()},
    )
    assert stolen.status_code == 403, stolen.text
    assert stolen.json()["detail"]["code"] == "DEVICE_MISMATCH"

    legit = await client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": tokens["refreshToken"], "deviceFingerprint": fp},
    )
    assert legit.status_code == 200, legit.text


async def test_admin_password_login_is_unaffected(client: AsyncClient):
    admin_headers = await _admin_headers(client)
    users = await client.get("/api/admin/v1/users", headers=admin_headers)
    assert users.status_code == 200, users.text
