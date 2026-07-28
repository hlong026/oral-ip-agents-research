"""硬件机器码多设备绑定契约测试（docs/19 §4.1）：
首绑/漂移、上限内自动绑定、超限申请幂等、审批/拒绝、单设备与全量解绑、
device_bind_limit 配置校验、存量指纹迁移。"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.core.security import decode_token, hash_password
from app.modules.auth.models import DeviceBindRequest, User, UserDevice
from tests.helpers import code_login, create_unused_code, reset_rate_limits


def _fp(prefix: str = "fp") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}.hash0001"


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


async def _set_limit(client: AsyncClient, headers: dict[str, str], value: str) -> int:
    r = await client.put(
        "/api/admin/v1/providers",
        headers=headers,
        json={"settings": {"device_bind_limit": value}},
    )
    return r.status_code


async def _devices_of(user_id: str) -> list[UserDevice]:
    async with SessionLocal() as db:
        rows = await db.execute(
            select(UserDevice).where(UserDevice.user_id == user_id).order_by(UserDevice.created_at.asc())
        )
        return list(rows.scalars().all())


async def _pending_count(user_id: str) -> int:
    async with SessionLocal() as db:
        return int(
            (
                await db.execute(
                    select(func.count(DeviceBindRequest.id)).where(
                        DeviceBindRequest.user_id == user_id,
                        DeviceBindRequest.status == "pending",
                    )
                )
            ).scalar()
            or 0
        )


async def test_first_login_binds_device_and_tolerates_drift(client: AsyncClient):
    """用例1：首次激活自动写入第一台设备；同设备段特征哈希漂移 → 成功且更新指纹"""
    code = await create_unused_code()
    device = f"fp-{uuid.uuid4().hex[:12]}"
    tokens = await code_login(client, code, fingerprint=f"{device}.hash-old")
    uid = _user_id(tokens)

    devices = await _devices_of(uid)
    assert len(devices) == 1
    assert devices[0].device_key == device
    assert devices[0].source == "web"

    await code_login(client, code, fingerprint=f"{device}.hash-new")
    devices = await _devices_of(uid)
    assert len(devices) == 1
    assert devices[0].fingerprint == f"{device}.hash-new"


async def test_new_device_auto_binds_within_limit(client: AsyncClient):
    """用例2：上限内新设备登录 → 自动绑定 +1，审计 device_auto_bound 存在"""
    admin = await _admin_headers(client)
    assert await _set_limit(client, admin, "2") == 200
    try:
        code = await create_unused_code()
        tokens = await code_login(client, code, fingerprint=_fp())
        uid = _user_id(tokens)
        await code_login(client, code, fingerprint=_fp())

        devices = await _devices_of(uid)
        assert len(devices) == 2
        async with SessionLocal() as db:
            audit = (
                await db.execute(
                    select(AuditLog).where(AuditLog.event == "device_auto_bound", AuditLog.user_id == uid)
                )
            ).scalars().all()
        assert len(audit) == 1
    finally:
        assert await _set_limit(client, admin, "1") == 200


async def test_limit_reached_creates_pending_request_idempotently(client: AsyncClient):
    """用例3：达上限 → 403 DEVICE_LIMIT_REACHED + pending 申请；重复登录不产生重复申请"""
    code = await create_unused_code()
    tokens = await code_login(client, code, fingerprint=_fp())
    uid = _user_id(tokens)

    new_device = _fp()
    for _ in range(2):
        r = await client.post("/api/v1/auth/login", json={"code": code, "deviceFingerprint": new_device})
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == "DEVICE_LIMIT_REACHED"
    assert await _pending_count(uid) == 1
    assert len(await _devices_of(uid)) == 1
    await reset_rate_limits()


async def test_admin_approve_unbinds_old_device_and_allows_rebind(client: AsyncClient):
    """用例4：approve（带 unbindDeviceId）→ 旧设备删除+会话吊销+申请 approved；新设备重登自动绑定"""
    code = await create_unused_code()
    old_fp = _fp()
    old_tokens = await code_login(client, code, fingerprint=old_fp)
    uid = _user_id(old_tokens)

    new_fp = _fp()
    r = await client.post("/api/v1/auth/login", json={"code": code, "deviceFingerprint": new_fp})
    assert r.status_code == 403
    await reset_rate_limits()

    admin = await _admin_headers(client)
    listed = await client.get("/api/admin/v1/device-requests?status=pending", headers=admin)
    assert listed.status_code == 200, listed.text
    request = next(item for item in listed.json()["items"] if item["userId"] == uid)
    assert request["activationCodeMasked"]
    old_device_id = request["boundDevices"][0]["id"]

    approved = await client.post(
        f"/api/admin/v1/device-requests/{request['id']}/approve",
        headers=admin,
        json={"unbindDeviceId": old_device_id},
    )
    assert approved.status_code == 200, approved.text

    # 旧设备行已删除，其 refresh 会话被吊销
    assert len(await _devices_of(uid)) == 0
    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": old_tokens["refreshToken"], "deviceFingerprint": old_fp},
    )
    assert refreshed.status_code == 401

    # 已处理申请不可重复处理
    again = await client.post(
        f"/api/admin/v1/device-requests/{request['id']}/approve", headers=admin, json={}
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "REQUEST_RESOLVED"

    # 新设备重登 → 自动绑定成功
    tokens = await code_login(client, code, fingerprint=new_fp)
    assert _user_id(tokens) == uid
    devices = await _devices_of(uid)
    assert len(devices) == 1
    assert devices[0].fingerprint == new_fp


async def test_admin_reject_keeps_new_device_blocked(client: AsyncClient):
    """用例5：reject → 新设备再登录仍 403（重新生成 pending 申请）"""
    code = await create_unused_code()
    tokens = await code_login(client, code, fingerprint=_fp())
    uid = _user_id(tokens)
    new_fp = _fp()

    r = await client.post("/api/v1/auth/login", json={"code": code, "deviceFingerprint": new_fp})
    assert r.status_code == 403

    admin = await _admin_headers(client)
    listed = await client.get("/api/admin/v1/device-requests?status=pending", headers=admin)
    request = next(item for item in listed.json()["items"] if item["userId"] == uid)
    rejected = await client.post(f"/api/admin/v1/device-requests/{request['id']}/reject", headers=admin)
    assert rejected.status_code == 200, rejected.text
    assert await _pending_count(uid) == 0

    r = await client.post("/api/v1/auth/login", json={"code": code, "deviceFingerprint": new_fp})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "DEVICE_LIMIT_REACHED"
    assert await _pending_count(uid) == 1
    await reset_rate_limits()


async def test_single_device_unbind_revokes_sessions(client: AsyncClient):
    """用例6：单设备解绑 → 该设备会话吊销（refresh 401）；他设备用未绑定指纹刷新 → DEVICE_MISMATCH"""
    admin = await _admin_headers(client)
    assert await _set_limit(client, admin, "2") == 200
    try:
        code = await create_unused_code()
        fp_a, fp_b = _fp(), _fp()
        tokens_a = await code_login(client, code, fingerprint=fp_a)
        tokens_b = await code_login(client, code, fingerprint=fp_b)
        uid = _user_id(tokens_a)

        devices = await _devices_of(uid)
        device_b = next(d for d in devices if d.fingerprint == fp_b)
        r = await client.post(f"/api/admin/v1/users/{uid}/devices/{device_b.id}/unbind", headers=admin)
        assert r.status_code == 200, r.text
        assert len(await _devices_of(uid)) == 1

        # B 的会话已吊销
        refreshed = await client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": tokens_b["refreshToken"], "deviceFingerprint": fp_b},
        )
        assert refreshed.status_code == 401

        # A 的有效会话拿未绑定指纹刷新 → DEVICE_MISMATCH
        mismatch = await client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": tokens_a["refreshToken"], "deviceFingerprint": fp_b},
        )
        assert mismatch.status_code == 403
        assert mismatch.json()["detail"]["code"] == "DEVICE_MISMATCH"
    finally:
        assert await _set_limit(client, admin, "1") == 200


async def test_unbind_all_devices_allows_fresh_rebind(client: AsyncClient):
    """用例7：全量解绑 → 设备清空，任意新设备可重新首绑"""
    code = await create_unused_code()
    tokens = await code_login(client, code, fingerprint=_fp())
    uid = _user_id(tokens)

    admin = await _admin_headers(client)
    r = await client.post(f"/api/admin/v1/users/{uid}/unbind-device", headers=admin)
    assert r.status_code == 200, r.text
    assert len(await _devices_of(uid)) == 0

    rebind_fp = _fp()
    rebound = await code_login(client, code, fingerprint=rebind_fp)
    assert _user_id(rebound) == uid
    devices = await _devices_of(uid)
    assert len(devices) == 1
    assert devices[0].fingerprint == rebind_fp


async def test_device_bind_limit_validation_and_no_kick_on_lower(client: AsyncClient):
    """用例8：非法值（0/11/非整数）保存被拒；调低上限后存量超额设备不被踢"""
    admin = await _admin_headers(client)
    for bad in ("0", "11", "abc"):
        assert await _set_limit(client, admin, bad) == 400, f"value={bad} 应被拒绝"

    assert await _set_limit(client, admin, "2") == 200
    try:
        code = await create_unused_code()
        fp_a, fp_b = _fp(), _fp()
        tokens = await code_login(client, code, fingerprint=fp_a)
        uid = _user_id(tokens)
        await code_login(client, code, fingerprint=fp_b)
        assert len(await _devices_of(uid)) == 2
    finally:
        assert await _set_limit(client, admin, "1") == 200

    # 上限调回 1 后，两台存量设备均可继续登录（匹配分支不受上限影响）
    for fp in (fp_a, fp_b):
        await code_login(client, code, fingerprint=fp)
    assert len(await _devices_of(uid)) == 2


def test_migration_moves_legacy_fingerprint(tmp_path: Path):
    """用例9：存量 users.device_fingerprint 经 dd5e6f7a8b9c 迁移正确搬入 user_devices

    迁移链中存在不兼容 sqlite 的历史迁移（非 batch alter），故隔离测试本次迁移：
    手建最小 users 表 → stamp 到前置版本 → 只升级 dd5e6f7a8b9c。"""
    import sqlite3

    server_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "migrate.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}

    def alembic(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=server_root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    # 最小 users 表（本迁移只读 id/device_fingerprint 两列）+ 存量旧指纹用户
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE users (id VARCHAR(32) PRIMARY KEY, device_fingerprint VARCHAR(128) NOT NULL)")
        conn.execute(
            "INSERT INTO users (id, device_fingerprint) VALUES (?, ?), (?, ?)",
            ("legacy-user-1", "hw-legacymachine0001.featurehash01", "legacy-user-2", ""),
        )
        conn.commit()
    finally:
        conn.close()

    alembic("stamp", "cc4d5e6f7a8b")
    alembic("upgrade", "dd5e6f7a8b9c")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT user_id, fingerprint, device_key, source FROM user_devices"
        ).fetchall()
    finally:
        conn.close()
    # 空指纹用户不搬迁，硬件码前缀判定 source=desktop-hw
    assert rows == [
        ("legacy-user-1", "hw-legacymachine0001.featurehash01", "hw-legacymachine0001", "desktop-hw")
    ]
