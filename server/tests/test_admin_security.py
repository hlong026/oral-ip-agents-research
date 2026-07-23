"""管理控制面安全回归：JWT 双密钥隔离 / 登录防爆破 / RBAC / 资金二次确认 / 同事务审计

覆盖 P1-P4 安全修复的行为契约：
- P1: 用户面密钥伪造的 aud=admin 令牌在管理面密钥验证阶段即失败（401）
- P2: 登录凭据错误按手机号 + IP 持久化计数，达限锁定后正确密码也 429；成功登录清零
- P3: RBAC 权限点（finance 调账 / auditor 只读 / ops 无套餐与角色管理）+ 资金类二次确认
- P4: 积分调整审计与业务同事务（业务失败时审计一并回滚）
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
from fastapi import HTTPException, status
from httpx import AsyncClient
from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.audit import AuditLog
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.deps import ADMIN_ROLES, ROLE_PERMISSIONS
from app.core.middleware import AdminApiAllowlistMiddleware, resolve_client_ip
from app.core.security import hash_password
from app.modules.auth.models import User


def _phone() -> str:
    return f"137{uuid.uuid4().hex[:8]}"


def _unique_ip() -> str:
    """独立 IP 主体：登录频控按手机号 + IP 计数，隔离后不影响其他用例。"""
    octets = uuid.uuid4().bytes
    return f"10.{octets[0]}.{octets[1]}.{octets[2]}"


async def _create_user(*, role: str) -> tuple[str, str]:
    phone = _phone()
    password = "Test@12345"
    async with SessionLocal() as db:
        user = User(
            phone=phone,
            password_hash=hash_password(password),
            nickname="安全测试",
            avatar_char="安",
            role=role,
            plan_type="trial" if role == "user" else "none",
            plan_expires_at=datetime.now(UTC) + timedelta(days=30) if role == "user" else None,
            activated_at=datetime.now(UTC),
        )
        db.add(user)
        await db.commit()
    return phone, password


async def _user_id_of(phone: str) -> str:
    async with SessionLocal() as db:
        return str((await db.execute(select(User.id).where(User.phone == phone))).scalar_one())


async def _create_plain_user_id() -> str:
    phone, _ = await _create_user(role="user")
    return await _user_id_of(phone)


async def _admin_login(client: AsyncClient, *, role: str) -> dict[str, str]:
    """管理面登录（任一 ADMIN_ROLES 角色），返回鉴权头。"""
    phone, password = await _create_user(role=role)
    response = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


# ---- P1: JWT 双密钥隔离 ----


def test_admin_roles_and_permission_mapping_are_consistent():
    assert ADMIN_ROLES == frozenset({"admin", "ops", "finance", "auditor"})
    assert ROLE_PERMISSIONS["admin"] == frozenset({"*"})
    assert "billing.adjust" in ROLE_PERMISSIONS["finance"]
    assert "billing.adjust" not in ROLE_PERMISSIONS["ops"]
    assert "catalog.manage" not in ROLE_PERMISSIONS["ops"]
    assert "activation.manage" in ROLE_PERMISSIONS["ops"]
    auditor_forbidden = {"users.write", "billing.adjust", "catalog.manage", "activation.manage", "im.manage"}
    assert not (auditor_forbidden & ROLE_PERMISSIONS["auditor"])


async def test_admin_token_forged_with_user_signing_key_is_rejected(client: AsyncClient):
    """威胁模型：用户面密钥泄露后，攻击者伪造 aud=admin 令牌 —— 管理面独立密钥必须拒绝。"""
    phone, _ = await _create_user(role="admin")
    user_id = await _user_id_of(phone)
    settings = get_settings()
    now = datetime.now(UTC)
    forged = pyjwt.encode(
        {
            "sub": user_id,
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "jti": uuid.uuid4().hex,
            "aud": "admin",
        },
        settings.app_secret,  # 用户面密钥：双密钥下无法通过管理面验证
        algorithm=settings.jwt_algorithm,
    )

    response = await client.get("/api/admin/v1/users", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


async def test_user_plane_token_of_admin_role_cannot_call_admin_api(client: AsyncClient):
    """即使 role=admin，从用户面签发的令牌（aud=user）也不能访问管理面。"""
    phone, password = await _create_user(role="admin")
    login = await client.post(
        "/api/v1/auth/login",
        json={"phone": phone, "password": password, "deviceId": "test"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}

    response = await client.get("/api/admin/v1/users", headers=headers)

    assert response.status_code == 401


async def test_admin_plane_token_cannot_call_user_api(client: AsyncClient):
    headers = await _admin_login(client, role="admin")

    response = await client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 401


async def test_plain_user_cannot_login_to_admin_console(client: AsyncClient):
    phone, password = await _create_user(role="user")

    response = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"


async def test_all_admin_roles_can_login_to_admin_console(client: AsyncClient):
    for role in ("admin", "ops", "finance", "auditor"):
        phone, password = await _create_user(role=role)
        response = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})
        assert response.status_code == 200, f"{role}: {response.text}"
        assert response.json()["accessToken"]


# ---- P2: 登录防爆破 ----


async def test_login_locks_out_after_repeated_bad_credentials(client: AsyncClient):
    """连续凭据错误达上限后锁定：锁定期内即使密码正确也 429，且手机号维度跨 IP 生效。"""
    phone, password = await _create_user(role="user")
    headers = {"X-Forwarded-For": _unique_ip()}
    limit = get_settings().login_failure_limit

    for attempt in range(limit):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"phone": phone, "password": "WrongPass!123", "deviceId": "test"},
            headers=headers,
        )
        assert resp.status_code == 401, f"attempt {attempt}: {resp.text}"

    locked = await client.post(
        "/api/v1/auth/login",
        json={"phone": phone, "password": password, "deviceId": "test"},
        headers=headers,
    )
    assert locked.status_code == 429
    assert locked.json()["detail"]["code"] == "LOGIN_RATE_LIMITED"

    # 换 IP 仍被手机号维度锁定拦截
    other_ip = await client.post(
        "/api/v1/auth/login",
        json={"phone": phone, "password": password, "deviceId": "test"},
        headers={"X-Forwarded-For": _unique_ip()},
    )
    assert other_ip.status_code == 429


async def test_successful_login_clears_failure_count(client: AsyncClient):
    """成功登录后失败计数清零：差一次达限时登录成功，之后重新计数不锁定。"""
    phone, password = await _create_user(role="user")
    headers = {"X-Forwarded-For": _unique_ip()}
    limit = get_settings().login_failure_limit

    for _ in range(limit - 1):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"phone": phone, "password": "WrongPass!123", "deviceId": "test"},
            headers=headers,
        )
        assert resp.status_code == 401

    ok = await client.post(
        "/api/v1/auth/login",
        json={"phone": phone, "password": password, "deviceId": "test"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text

    # 计数已清零：再失败 limit-1 次不应锁定
    for _ in range(limit - 1):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"phone": phone, "password": "WrongPass!123", "deviceId": "test"},
            headers=headers,
        )
        assert resp.status_code == 401
    still_ok = await client.post(
        "/api/v1/auth/login",
        json={"phone": phone, "password": password, "deviceId": "test"},
        headers=headers,
    )
    assert still_ok.status_code == 200, still_ok.text


async def test_admin_login_is_also_rate_limited(client: AsyncClient):
    """管理面登录同样接入防爆破（同一 guard）。"""
    phone, password = await _create_user(role="admin")
    headers = {"X-Forwarded-For": _unique_ip()}
    limit = get_settings().login_failure_limit

    for _ in range(limit):
        resp = await client.post(
            "/api/admin/v1/auth/login",
            json={"phone": phone, "password": "WrongPass!123"},
            headers=headers,
        )
        assert resp.status_code == 401

    locked = await client.post(
        "/api/admin/v1/auth/login",
        json={"phone": phone, "password": password},
        headers=headers,
    )
    assert locked.status_code == 429


# ---- P3: RBAC 路由级权限 ----


async def test_auditor_is_read_only_and_cannot_adjust_credits(client: AsyncClient):
    auditor_headers = await _admin_login(client, role="auditor")
    target_id = await _create_plain_user_id()

    audit_feed = await client.get("/api/admin/v1/audit", headers=auditor_headers)
    users = await client.get("/api/admin/v1/users", headers=auditor_headers)
    adjust = await client.post(
        f"/api/admin/v1/users/{target_id}/credits/adjust",
        headers=auditor_headers,
        json={"points": 100, "reason": "审计员不应能调账"},
    )
    batch = await client.post(
        "/api/admin/v1/activation/batches",
        headers=auditor_headers,
        json={"name": "越权批次", "skuVersionId": "any", "count": 1},
    )

    assert audit_feed.status_code == 200
    assert users.status_code == 200
    assert adjust.status_code == 403
    assert batch.status_code == 403


async def test_finance_can_adjust_credits_but_cannot_manage_users(client: AsyncClient):
    finance_headers = await _admin_login(client, role="finance")
    target_id = await _create_plain_user_id()

    adjust = await client.post(
        f"/api/admin/v1/users/{target_id}/credits/adjust",
        headers=finance_headers,
        json={"points": 100, "reason": "财务补发积分"},
    )
    disable = await client.patch(
        f"/api/admin/v1/users/{target_id}",
        headers=finance_headers,
        json={"isActive": False},
    )

    assert adjust.status_code == 200, adjust.text
    assert adjust.json()["balance"] == 100
    assert disable.status_code == 403


async def test_ops_cannot_manage_catalog_or_change_roles(client: AsyncClient):
    ops_headers = await _admin_login(client, role="ops")
    target_id = await _create_plain_user_id()

    create_plan = await client.post(
        "/api/admin/v1/plans",
        headers=ops_headers,
        json={
            "code": f"RBAC_{uuid.uuid4().hex[:8].upper()}",
            "name": "越权套餐",
            "subtitle": "ops 不应能创建",
            "description": "RBAC 验证",
            "badge": "",
            "skuType": "annual_bundle",
            "audience": "public",
            "durationDays": 365,
            "monthlyPoints": 1000,
            "oneTimePoints": 0,
            "listPriceCents": 199900,
            "displayPriceCents": 169900,
            "entitlements": ["digital_human"],
            "maxConcurrency": 2,
            "maxResolution": "1080p",
            "purchaseInstructions": "联系管理员",
        },
    )
    change_role = await client.patch(
        f"/api/admin/v1/users/{target_id}",
        headers=ops_headers,
        json={"role": "finance"},
    )
    disable = await client.patch(
        f"/api/admin/v1/users/{target_id}",
        headers=ops_headers,
        json={"isActive": False},
    )

    assert create_plan.status_code == 403
    assert change_role.status_code == 403
    assert change_role.json()["detail"]["code"] == "FORBIDDEN"
    # ops 有 users.write：停用账号允许，仅角色变更限定超管
    assert disable.status_code == 200, disable.text


# ---- P3: 资金类二次确认 + P4: 同事务审计 ----


async def test_credit_adjust_requires_confirm_for_large_or_negative_amounts(client: AsyncClient):
    admin_headers = await _admin_login(client, role="admin")
    target_id = await _create_plain_user_id()

    big = await client.post(
        f"/api/admin/v1/users/{target_id}/credits/adjust",
        headers=admin_headers,
        json={"points": 10_000, "reason": "大额发放未确认"},
    )
    assert big.status_code == 409
    assert big.json()["detail"]["code"] == "CONFIRM_REQUIRED"

    seeded = await client.post(
        f"/api/admin/v1/users/{target_id}/credits/adjust",
        headers=admin_headers,
        json={"points": 100, "reason": "预存积分"},
    )
    assert seeded.status_code == 200, seeded.text

    deduct = await client.post(
        f"/api/admin/v1/users/{target_id}/credits/adjust",
        headers=admin_headers,
        json={"points": -30, "reason": "扣减未确认"},
    )
    assert deduct.status_code == 409
    assert deduct.json()["detail"]["code"] == "CONFIRM_REQUIRED"

    confirmed = await client.post(
        f"/api/admin/v1/users/{target_id}/credits/adjust",
        headers=admin_headers,
        json={"points": -30, "reason": "扣减已确认", "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["balance"] == 70


async def test_ops_cannot_disable_admin_accounts(client: AsyncClient):
    """M2：ops 拥有 users.write 但不得停用/启用管理账号（防管理面自锁）。"""
    ops_headers = await _admin_login(client, role="ops")
    admin_phone, _ = await _create_user(role="admin")
    target_admin_id = await _user_id_of(admin_phone)

    disable_admin = await client.patch(
        f"/api/admin/v1/users/{target_admin_id}",
        headers=ops_headers,
        json={"isActive": False},
    )

    assert disable_admin.status_code == 403
    assert disable_admin.json()["detail"]["code"] == "FORBIDDEN"


async def test_super_admin_can_disable_admin_accounts(client: AsyncClient):
    admin_headers = await _admin_login(client, role="admin")
    ops_phone, _ = await _create_user(role="ops")
    target_ops_id = await _user_id_of(ops_phone)

    disabled = await client.patch(
        f"/api/admin/v1/users/{target_ops_id}",
        headers=admin_headers,
        json={"isActive": False},
    )

    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["isActive"] is False


async def test_credit_adjustment_writes_audit_log_in_same_transaction(client: AsyncClient):
    admin_headers = await _admin_login(client, role="admin")
    target_id = await _create_plain_user_id()

    resp = await client.post(
        f"/api/admin/v1/users/{target_id}/credits/adjust",
        headers=admin_headers,
        json={"points": 50, "reason": "审计落库验证"},
    )
    assert resp.status_code == 200, resp.text

    async with SessionLocal() as db:
        rows = (await db.execute(select(AuditLog).where(AuditLog.event == "admin_credit_adjusted"))).scalars().all()
    assert any(f"target={target_id}" in row.detail for row in rows)


async def test_credit_adjustment_audit_rolls_back_when_business_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """业务失败时审计随事务回滚，不留半成品记录（同事务语义）。"""
    from app.modules.billing import service as billing_service

    async def failing_adjust(*_args, **_kwargs):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "SETTLEMENT_DOWN", "message": "结算失败"},
        )

    monkeypatch.setattr(billing_service, "adjust_points", failing_adjust)

    admin_headers = await _admin_login(client, role="admin")
    target_id = await _create_plain_user_id()

    def _credit_audit_count():
        return select(func.count(AuditLog.id)).where(AuditLog.event == "admin_credit_adjusted")

    async with SessionLocal() as db:
        before = int((await db.execute(_credit_audit_count())).scalar_one())

    resp = await client.post(
        f"/api/admin/v1/users/{target_id}/credits/adjust",
        headers=admin_headers,
        json={"points": 50, "reason": "失败回滚验证"},
    )
    assert resp.status_code == 503

    async with SessionLocal() as db:
        after = int((await db.execute(_credit_audit_count())).scalar_one())
    # 前后计数一致：失败的业务操作没有留下任何审计记录（防空洞断言，独立运行也成立）
    assert after == before


# ---- M1: 管理面 IP 白名单 + XFF 受信策略 ----


def _admin_request(client_host: str, xff: str | None = None, path: str = "/api/admin/v1/users") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": (client_host, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


async def _allowlist_dispatch(allowed: list[str], request: Request) -> Response:
    middleware = AdminApiAllowlistMiddleware(lambda scope, receive, send: None, allowed_networks=allowed)

    async def call_next(_request: Request) -> Response:
        return JSONResponse({"ok": True})

    return await middleware.dispatch(request, call_next)


async def test_allowlist_allows_all_when_empty():
    response = await _allowlist_dispatch([], _admin_request("203.0.113.7"))
    assert response.status_code == 200


async def test_allowlist_allows_listed_cidr_and_rejects_unlisted():
    allowed = await _allowlist_dispatch(["203.0.113.0/24"], _admin_request("203.0.113.7"))
    rejected = await _allowlist_dispatch(["10.0.0.0/8"], _admin_request("203.0.113.7"))
    assert allowed.status_code == 200
    assert rejected.status_code == 403


async def test_allowlist_does_not_block_user_plane():
    response = await _allowlist_dispatch(["10.0.0.0/8"], _admin_request("203.0.113.7", path="/api/v1/auth/login"))
    assert response.status_code == 200


async def test_allowlist_ignores_spoofed_xff_from_untrusted_peer(monkeypatch: pytest.MonkeyPatch):
    """公网直连（非受信代理）伪造 XFF 为白名单网段：不采信，仍按直连 IP 拒绝。"""
    monkeypatch.setattr(get_settings(), "trusted_proxy_ips", "")
    response = await _allowlist_dispatch(["10.0.0.0/8"], _admin_request("203.0.113.7", xff="10.1.2.3"))
    assert response.status_code == 403


async def test_allowlist_honors_xff_from_trusted_proxy(monkeypatch: pytest.MonkeyPatch):
    """反向代理部署：直连对端属于受信代理时采信 XFF 最左地址判定。"""
    monkeypatch.setattr(get_settings(), "trusted_proxy_ips", "127.0.0.1")
    response = await _allowlist_dispatch(["10.0.0.0/8"], _admin_request("127.0.0.1", xff="10.1.2.3"))
    assert response.status_code == 200


def test_resolve_client_ip_uses_xff_only_from_trusted_proxy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_ips", "127.0.0.0/8")
    trusted = _admin_request("127.0.0.1", xff="10.1.2.3, 192.168.1.1")
    assert resolve_client_ip(trusted) == "10.1.2.3"

    monkeypatch.setattr(get_settings(), "trusted_proxy_ips", "")
    untrusted = _admin_request("203.0.113.7", xff="10.1.2.3")
    assert resolve_client_ip(untrusted) == "203.0.113.7"


# ---- refresh 令牌跨面契约 ----


async def test_admin_refresh_token_keeps_admin_audience_after_refresh(client: AsyncClient):
    """管理面 refresh 令牌换发后保持 aud=admin：可访问管理面，不能访问用户面。"""
    phone, password = await _create_user(role="admin")
    login = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})
    assert login.status_code == 200, login.text

    refreshed = await client.post("/api/v1/auth/refresh", json={"refreshToken": login.json()["refreshToken"]})
    assert refreshed.status_code == 200, refreshed.text
    new_access = refreshed.json()["accessToken"]

    admin_api = await client.get("/api/admin/v1/users", headers={"Authorization": f"Bearer {new_access}"})
    user_api = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert admin_api.status_code == 200
    assert user_api.status_code == 401


async def test_refresh_token_forged_with_user_signing_key_is_rejected(client: AsyncClient):
    """伪造 aud=admin 的 refresh（用户面密钥签名）：audience 自动识别分支选管理面密钥，验证失败。"""
    settings = get_settings()
    now = datetime.now(UTC)
    forged = pyjwt.encode(
        {
            "sub": uuid.uuid4().hex,
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=1)).timestamp()),
            "jti": uuid.uuid4().hex,
            "aud": "admin",
        },
        settings.app_secret,
        algorithm=settings.jwt_algorithm,
    )

    resp = await client.post("/api/v1/auth/refresh", json={"refreshToken": forged})

    assert resp.status_code == 401