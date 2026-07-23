"""冒烟测试（§8 质量规范：pytest，mock provider 开箱可跑）

覆盖：
- W1–W2 验收「登录联通」：注册 → me → 额度真实余额（F-601/F-602）
- 合规红线：克隆无 consent_token 被拒绝（C8/C10）
- F-405：统一 PipelineTask 模型 8 步状态机 + 取消
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import User

STEP_ORDER = ["parse", "asr", "rewrite", "voice", "avatar", "compose", "edit", "publish"]


def _phone() -> str:
    return f"139{uuid.uuid4().hex[:8]}"


async def _register(client: AsyncClient, phone: str, role: str = "user") -> dict:
    password = "Test@12345"
    async with SessionLocal() as db:
        user = User(
            phone=phone,
            password_hash=hash_password(password),
            nickname="冒烟测试",
            avatar_char="冒",
            role=role,
            plan_type="trial",
            plan_expires_at=datetime.now(UTC) + timedelta(days=30),
            activated_at=datetime.now(UTC),
        )
        db.add(user)
        await db.flush()
        from app.modules.billing.service import grant_initial_quota
        from app.modules.ipasset.service import create_default_persona

        await grant_initial_quota(db, user.id)
        await create_default_persona(db, user.id, user.nickname)
        await db.commit()
    path = "/api/admin/v1/auth/login" if role == "admin" else "/api/v1/auth/login"
    r = await client.post(path, json={"phone": phone, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


async def _pipeline_quote(client: AsyncClient, user_headers: dict) -> str:
    """为冒烟任务发布完整测试价目，并按服务端任务合同取得报价。"""
    admin_headers = _auth(await _register(client, _phone(), role="admin"))
    created = await client.post(
        "/api/admin/v1/price-versions",
        headers=admin_headers,
        json={"version": f"smoke-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]
    modules = ["topic_generation", "script_generation", "tts", "digital_human", "hd_export"]
    for module in modules:
        configured = await client.put(
            f"/api/admin/v1/price-versions/{version_id}/modules/{module}",
            headers=admin_headers,
            json={
                "displayName": module,
                "billingUnit": "per_action",
                "unitSize": 1,
                "pointsPerUnit": 1,
                "minimumPoints": 1,
                "enabled": True,
            },
        )
        assert configured.status_code == 200, configured.text
    published = await client.post(
        f"/api/admin/v1/price-versions/{version_id}/publish",
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text
    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=user_headers,
        json={"items": [{"module": module, "quantity": 1} for module in modules]},
    )
    assert quote.status_code == 200, quote.text
    return quote.json()["quoteId"]


async def test_healthz(client: AsyncClient):
    r = await client.get("/healthz")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert "storage" in r.json()


async def test_readyz_reports_dependency_state(client: AsyncClient, monkeypatch):
    from app.core import events, storage

    async def ready() -> bool:
        return True

    monkeypatch.setattr(events, "redis_ready", ready, raising=False)
    monkeypatch.setattr(storage, "storage_ready", ready, raising=False)

    r = await client.get("/readyz")

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "database": True, "redis": True, "storage": True}


async def test_readyz_fails_closed_when_redis_is_unavailable(client: AsyncClient, monkeypatch):
    from app.core import events, storage

    async def unavailable() -> bool:
        return False

    async def ready() -> bool:
        return True

    monkeypatch.setattr(events, "redis_ready", unavailable, raising=False)
    monkeypatch.setattr(storage, "storage_ready", ready, raising=False)

    r = await client.get("/readyz")

    assert r.status_code == 503
    assert r.json().get("detail") == {
        "code": "NOT_READY",
        "database": True,
        "redis": False,
        "storage": True,
    }, r.text


async def test_readyz_fails_closed_when_storage_is_unavailable(client: AsyncClient, monkeypatch):
    from app.core import events, storage

    async def ready() -> bool:
        return True

    async def unavailable() -> bool:
        return False

    monkeypatch.setattr(events, "redis_ready", ready, raising=False)
    monkeypatch.setattr(storage, "storage_ready", unavailable, raising=False)

    r = await client.get("/readyz")

    assert r.status_code == 503
    assert r.json().get("detail") == {
        "code": "NOT_READY",
        "database": True,
        "redis": True,
        "storage": False,
    }, r.text


async def test_auth_and_quota_flow(client: AsyncClient):
    """里程碑：登录联通（注册赠额度 → JWT → me → 额度卡真实余额）"""
    phone = _phone()
    tokens = await _register(client, phone)

    r = await client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert r.status_code == 200
    assert r.json()["phone"] == phone

    r = await client.get("/api/v1/billing/quota", headers=_auth(tokens))
    assert r.status_code == 200
    assert r.json()["balance"] > 0  # 开户礼初始额度


async def test_login_wrong_password_rejected(client: AsyncClient):
    phone = _phone()
    await _register(client, phone)
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": "wrong-pass"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "BAD_CREDENTIALS"


async def test_unauthorized_without_token(client: AsyncClient):
    r = await client.get("/api/v1/billing/quota")
    assert r.status_code == 401


async def test_clone_requires_consent(client: AsyncClient):
    """合规红线：声音克隆无授权凭证 → 422 CONSENT_REQUIRED"""
    tokens = await _register(client, _phone())
    r = await client.post(
        "/api/v1/voices/clone",
        data={"name": "未授权音色", "consentToken": "   "},  # 空白凭证视同缺失（httpx 会丢弃空串表单域）
        files={"file": ("sample.wav", b"RIFF" + b"\x00" * 64, "audio/wav")},
        headers=_auth(tokens),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "CONSENT_REQUIRED"


async def test_avatar_clone_requires_consent(client: AsyncClient):
    """合规红线：形象克隆无授权凭证 → 422 CONSENT_REQUIRED"""
    tokens = await _register(client, _phone())
    r = await client.post(
        "/api/v1/avatars/clone",
        data={"name": "未授权形象", "consentToken": "  "},
        files={"file": ("train.mp4", b"\x00" * 128, "video/mp4")},
        headers=_auth(tokens),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "CONSENT_REQUIRED"


async def test_pipeline_create_fetch_cancel(client: AsyncClient):
    """F-405：统一 PipelineTask 模型（8 步状态机）创建/查询/取消"""
    tokens = await _register(client, _phone())
    h = _auth(tokens)

    r = await client.get("/api/v1/personas", headers=h)
    assert r.status_code == 200
    persona_id = r.json()[0]["id"]  # 注册即建默认 IP 档案
    quote_id = await _pipeline_quote(client, h)

    r = await client.post(
        "/api/v1/pipelines",
        json={
            "ipId": persona_id,
            "topic": "如何做好一碗牛肉面",
            "mode": "manual",
            "quoteId": quote_id,
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    tasks = r.json()
    assert len(tasks) == 1
    task = tasks[0]
    assert [s["step"] for s in task["steps"]] == STEP_ORDER
    assert task["compute"] == "cloud"  # CLOUD_FIRST

    tid = task["id"]
    r = await client.get(f"/api/v1/pipelines/{tid}", headers=h)
    assert r.status_code == 200
    assert r.json()["id"] == tid

    r = await client.post(f"/api/v1/pipelines/{tid}/cancel", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"


async def test_pipeline_batch_fanout(client: AsyncClient):
    """F-406：批量扇出共享 batchId"""
    tokens = await _register(client, _phone())
    h = _auth(tokens)
    r = await client.get("/api/v1/personas", headers=h)
    persona_id = r.json()[0]["id"]
    quote_id = await _pipeline_quote(client, h)

    r = await client.post(
        "/api/v1/pipelines",
        json={"ipId": persona_id, "topic": "批量选题", "count": 3, "quoteId": quote_id},
        headers=h,
    )
    assert r.status_code == 200, r.text
    tasks = r.json()
    assert len(tasks) == 3
    batch_ids = {t["batchId"] for t in tasks}
    assert len(batch_ids) == 1 and batch_ids.pop() is not None

    for t in tasks:
        await client.post(f"/api/v1/pipelines/{t['id']}/cancel", headers=h)
