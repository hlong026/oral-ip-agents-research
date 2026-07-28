"""发布全链路回归：扫码授权 → 会话加密持久化 → 昵称落库 → 发布执行 → Cookie 回写。

审查口径（F-501~F-504）：
1. 扫码轮询：waiting → success，账号落库且 session 密文存储、昵称取驱动抓取值
2. 发布任务：publish_task_video 建任务并入队（_schedule_job 打桩，不依赖 Redis）
3. 发布执行：_run_job 成功后 status=success、postIdSource=internal、刷新后的 Cookie 回写 DB
4. 失败护栏：账号过期任务直接 failed，不触发驱动发布
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.modules.publish import repository as repo
from app.modules.publish import service as publish_service
from app.modules.publish.session_crypto import is_encrypted_session
from app.providers.registry import registry


class FakeDriver:
    """模拟 SAU 驱动：第二次轮询登录成功；publish 刷新 Cookie 并返回内部追踪号"""

    def __init__(self) -> None:
        self.polls = 0
        self.published_with: dict[str, Any] | None = None

    async def qrcode_login(self) -> dict[str, str]:
        return {"ticket": "tk-full-flow", "qrcodeUrl": "data:image/png;base64,qr"}

    async def check_login(self, ticket: str) -> dict[str, Any] | None:
        if ticket != "tk-full-flow":
            return None  # 未知票据：与真实驱动语义对齐
        self.polls += 1
        if self.polls == 1:
            return {"_waiting": True, "qrcode_url": "data:image/png;base64,qr2"}
        return {
            "cookies": [{"name": "sessionid", "value": "cookie-v1"}],
            "nickname": "全链路测试号",
        }

    async def publish(
        self,
        account_session: dict[str, Any],
        video_key: str,
        title: str,
        topics: list[str],
        cover_key: str | None,
        scheduled_at: str | None = None,
        account_id: str = "",
    ) -> str:
        self.published_with = {
            "session": dict(account_session),
            "video_key": video_key,
            "title": title,
            "scheduled_at": scheduled_at,
        }
        # 模拟 SAU 发布过程中平台刷新 Cookie（base_driver 会原地更新 session）
        account_session["cookies"] = [{"name": "sessionid", "value": "cookie-v2"}]
        return "dy_00000001"


@pytest.fixture
def fake_driver(monkeypatch: pytest.MonkeyPatch) -> FakeDriver:
    driver = FakeDriver()
    monkeypatch.setattr(registry, "publish_driver", lambda platform: driver)
    monkeypatch.setattr(
        publish_service,
        "_capability",
        lambda platform: SimpleNamespace(automaticEnabled=True, reason="", mode="automatic", platform=platform),
    )
    monkeypatch.setattr(publish_service, "_schedule_job", lambda job_id, scheduled_at="": "msg-test")
    return driver


@pytest.mark.asyncio
async def test_qrcode_login_persists_encrypted_session_and_nickname(client, fake_driver: FakeDriver) -> None:
    user_id = uuid.uuid4().hex
    start = await publish_service.qrcode_start("douyin")
    assert start.ticket == "tk-full-flow"
    assert start.qrcodeUrl

    async with SessionLocal() as db:
        first = await publish_service.qrcode_poll(db, user_id, "douyin", start.ticket)
        assert first.status == "waiting"
        # 二维码过期刷新后前端应拿到新图
        assert first.qrcodeUrl == "data:image/png;base64,qr2"

        second = await publish_service.qrcode_poll(db, user_id, "douyin", start.ticket)
        assert second.status == "success"
        assert second.account is not None
        assert second.account.nickname == "全链路测试号"

        account = await repo.get_account(db, second.account.id, user_id)
        assert account is not None
        # 持久化审查：session 必须密文落库，明文 Cookie 不得出现
        assert is_encrypted_session(account.session_json)
        assert "cookie-v1" not in account.session_json
        assert repo.account_session(account)["cookies"][0]["value"] == "cookie-v1"


@pytest.mark.asyncio
async def test_publish_job_success_writes_back_refreshed_cookie(client, fake_driver: FakeDriver) -> None:
    from app.core.storage import save_bytes

    user_id = uuid.uuid4().hex
    video_key = await save_bytes("final", f"{uuid.uuid4().hex}.mp4", b"fake-mp4")

    async with SessionLocal() as db:
        account = await repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="全链路测试号",
            session_json=json.dumps({"cookies": [{"name": "sessionid", "value": "cookie-v1"}]}),
            status="active",
        )
        job_ids = await publish_service.publish_task_video(
            db,
            user_id,
            task_id=uuid.uuid4().hex,
            platforms=["douyin"],
            title="全链路成片",
            video_key=video_key,
            cover_key=None,
            render_version_id=uuid.uuid4().hex,
            render_version=1,
        )
        assert len(job_ids) == 1
        job = await repo.get_job(db, job_ids[0], user_id)
        assert job is not None
        assert job.status == "queued"
        assert job.account_id == account.id

    await publish_service._run_job(job_ids[0])

    async with SessionLocal() as db:
        job = await repo.get_job(db, job_ids[0], user_id)
        assert job is not None
        assert job.status == "success"
        assert job.post_id == "dy_00000001"
        # SAU 拿不到平台作品 ID，必须标记为内部追踪号
        assert job.post_id_source == "internal"

        refreshed = await repo.get_account(db, account.id, user_id)
        assert refreshed is not None
        assert is_encrypted_session(refreshed.session_json)
        # 发布中平台刷新的 Cookie 必须回写（且仍为密文）
        assert repo.account_session(refreshed)["cookies"][0]["value"] == "cookie-v2"

    assert fake_driver.published_with is not None
    assert fake_driver.published_with["video_key"] == video_key
    # 发布时驱动拿到的是扫码落库的原始 Cookie
    assert fake_driver.published_with["session"]["cookies"][0]["value"] == "cookie-v1"
    # 定时双重调度护栏：队列延迟到点后立即发布，不得再把已到点时间透传给平台侧定时
    assert fake_driver.published_with["scheduled_at"] is None


@pytest.mark.asyncio
async def test_unknown_ticket_poll_returns_expired(client, fake_driver: FakeDriver) -> None:
    """服务重启丢失登录会话/票据已消费：必须返回 expired 终止轮询，而非永远 waiting"""
    async with SessionLocal() as db:
        result = await publish_service.qrcode_poll(db, uuid.uuid4().hex, "douyin", "tk-unknown")
    assert result.status == "expired"
    assert result.message


@pytest.mark.asyncio
async def test_reauth_updates_account_in_place(client, fake_driver: FakeDriver) -> None:
    """重新授权：扫码成功后原地更新旧账号，不产生重复账号、失效告警消除"""
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        old = await repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="旧昵称",
            session_json=json.dumps({"cookies": [{"name": "sessionid", "value": "stale"}]}),
            status="expired",
        )
        started = await publish_service.reauth_account(db, user_id, old.id)
        assert started.ticket == "tk-full-flow"

        first = await publish_service.qrcode_poll(db, user_id, "douyin", started.ticket)
        assert first.status == "waiting"
        second = await publish_service.qrcode_poll(db, user_id, "douyin", started.ticket)
        assert second.status == "success"
        assert second.account is not None
        # 同一条账号记录被原地更新
        assert second.account.id == old.id

        accounts = await repo.list_accounts(db, user_id)
        assert len(accounts) == 1
        refreshed = accounts[0]
        assert refreshed.status == "active"
        assert refreshed.nickname == "全链路测试号"
        assert repo.account_session(refreshed)["cookies"][0]["value"] == "cookie-v1"


@pytest.mark.asyncio
async def test_retry_rebinds_latest_active_account(client, fake_driver: FakeDriver) -> None:
    """失败任务重试：原账号失效时自动重绑该平台最新 active 账号"""
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        expired_acc = await repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="失效账号",
            session_json="{}",
            status="expired",
        )
        fresh_acc = await repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="新授权账号",
            session_json="{}",
            status="active",
        )
        job = await repo.create_job(
            db,
            user_id=user_id,
            task_id=uuid.uuid4().hex,
            account_id=expired_acc.id,
            platform="douyin",
            title="重试链路",
            video_key="final/na.mp4",
            status="failed",
        )

        out = await publish_service.retry_job(db, user_id, job.id)
        assert out.status == "queued"
        rebound = await repo.get_job(db, job.id, user_id)
        assert rebound is not None
        assert rebound.account_id == fresh_acc.id


class RaceDriver:
    """模拟并发轮询竞态：胜者在读 Cookie 时让出事件循环，败者拿到 None"""

    def __init__(self) -> None:
        self.consumed = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def qrcode_login(self) -> dict[str, str]:
        return {"ticket": "tk-race", "qrcodeUrl": "data:image/png;base64,qr"}

    async def check_login(self, ticket: str) -> dict[str, Any] | None:
        if self.consumed:
            return None  # 登录会话已被胜者原子摘除
        self.consumed = True
        self.entered.set()
        await self.release.wait()  # 模拟 base_driver 读 Cookie 文件的 await 窗口
        return {"cookies": [{"name": "sessionid", "value": "race-v1"}], "nickname": "竞态胜者号"}


@pytest.mark.asyncio
async def test_reauth_survives_concurrent_poll_race(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """并发轮询竞态：败者拿到 None 不得清除 reauth 绑定，胜者仍须原地更新旧账号"""
    driver = RaceDriver()
    monkeypatch.setattr(registry, "publish_driver", lambda platform: driver)
    monkeypatch.setattr(
        publish_service,
        "_capability",
        lambda platform: SimpleNamespace(automaticEnabled=True, reason="", mode="automatic", platform=platform),
    )
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        old = await repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="旧昵称",
            session_json="{}",
            status="expired",
        )
        started = await publish_service.reauth_account(db, user_id, old.id)

    async def winner_poll():
        async with SessionLocal() as db:
            return await publish_service.qrcode_poll(db, user_id, "douyin", started.ticket)

    winner = asyncio.create_task(winner_poll())
    await asyncio.wait_for(driver.entered.wait(), timeout=2)
    # 胜者挂起在 await 窗口内，败者并发轮询拿到 None → expired
    async with SessionLocal() as db:
        loser = await publish_service.qrcode_poll(db, user_id, "douyin", started.ticket)
    assert loser.status == "expired"
    driver.release.set()
    result = await asyncio.wait_for(winner, timeout=2)
    assert result.status == "success"
    assert result.account is not None
    # 绑定未被败者误清：仍是原地更新，不新建重复账号
    assert result.account.id == old.id
    async with SessionLocal() as db:
        accounts = await repo.list_accounts(db, user_id)
        assert len(accounts) == 1
        assert accounts[0].status == "active"


def test_reauth_binding_expires_by_ttl() -> None:
    """reauth 绑定带 TTL：过期后读取返回空并惰性清理，不永久驻留"""
    publish_service._REAUTH_TICKETS["tk-ttl"] = ("acc-1", datetime.now(UTC) - timedelta(seconds=1))
    assert publish_service._reauth_binding("tk-ttl") == ""
    assert "tk-ttl" not in publish_service._REAUTH_TICKETS
    publish_service._REAUTH_TICKETS["tk-live"] = ("acc-2", datetime.now(UTC) + timedelta(minutes=5))
    assert publish_service._reauth_binding("tk-live") == "acc-2"
    publish_service._REAUTH_TICKETS.pop("tk-live", None)


@pytest.mark.asyncio
async def test_publish_job_fails_fast_when_account_expired(client, fake_driver: FakeDriver) -> None:
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        account = await repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="过期账号",
            session_json="{}",
            status="active",
        )
        job_ids = await publish_service.publish_task_video(
            db,
            user_id,
            task_id=uuid.uuid4().hex,
            platforms=["douyin"],
            title="过期链路",
            video_key="final/na.mp4",
            cover_key=None,
        )
        acc = await repo.get_account(db, account.id, user_id)
        assert acc is not None
        acc.status = "expired"
        await repo.save_account(db, acc)

    await publish_service._run_job(job_ids[0])

    async with SessionLocal() as db:
        job = await repo.get_job(db, job_ids[0], user_id)
        assert job is not None
        assert job.status == "failed"
        assert "登录态失效" in job.error
    # 过期账号绝不能触发真实发布
    assert fake_driver.published_with is None


@pytest.mark.asyncio
async def test_unauthorized_platform_creates_failed_job_with_guidance(client, fake_driver: FakeDriver) -> None:
    """未扫码授权时：任务落 failed 并引导用户去授权，而不是静默丢弃"""
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        job_ids = await publish_service.publish_task_video(
            db,
            user_id,
            task_id=uuid.uuid4().hex,
            platforms=["douyin"],
            title="未授权链路",
            video_key="final/na.mp4",
            cover_key=None,
        )
        job = await repo.get_job(db, job_ids[0], user_id)
        assert job is not None
        assert job.status == "failed"
        assert "扫码授权" in job.error


@pytest.mark.asyncio
async def test_title_truncated_per_platform_limit(client, fake_driver: FakeDriver) -> None:
    """平台感知限长：同一标题广播多平台时，抖音按 30 字、小红书按 20 字截断落库，
    保证 job.title 与 SAU 上传器实际发出的一致（小红书上传器兜底 [:20]）"""
    user_id = uuid.uuid4().hex
    long_title = "这是一条超过二十个字但不足三十个字的发布标题用于验证"
    assert 20 < len(long_title) <= 30
    async with SessionLocal() as db:
        for platform in ("douyin", "xiaohongshu"):
            await repo.create_account(
                db,
                user_id=user_id,
                platform=platform,
                nickname=f"限长测试-{platform}",
                session_json=json.dumps({"cookies": [{"name": "sessionid", "value": "cookie-v1"}]}),
                status="active",
            )
        job_ids = await publish_service.publish_task_video(
            db,
            user_id,
            task_id=uuid.uuid4().hex,
            platforms=["douyin", "xiaohongshu"],
            title=long_title,
            video_key="final/limit.mp4",
            cover_key=None,
        )
        titles = {}
        for jid in job_ids:
            job = await repo.get_job(db, jid, user_id)
            assert job is not None
            titles[job.platform] = job.title
    # 抖音 30 字预算内不截断；小红书按 20 字限长在建任务时可控截断，不留给上传器静默腰斩
    assert titles["douyin"] == long_title
    assert titles["xiaohongshu"] == long_title[:20]
