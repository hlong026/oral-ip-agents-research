"""云端历史克隆声音找回：列表去重比对 + 一键导入（feat voice cloud recovery）"""

import pytest_asyncio

from app.core.db import SessionLocal, init_models
from app.modules.voice.models import Voice
from app.providers.registry import registry
from tests.helpers import code_login, create_unused_code

CLOUD_ITEMS = [
    {"voice": "cloud-voice-aaa", "type": 8, "title": "裴火荣", "rate": "1.1", "volume": "1.0", "pitch": "0.9"},
    {"voice": "cloud-voice-bbb", "type": 8, "title": "裴火荣", "rate": "1.0", "volume": "1.0", "pitch": "1.0"},
]


def _cloud_items(prefix: str) -> list[dict]:
    """测试间共用同一个 sqlite 库：cloudId 按用例前缀隔离，避免跨用例认领污染"""
    return [{**item, "voice": item["voice"].replace("cloud-voice", prefix)} for item in CLOUD_ITEMS]


@pytest_asyncio.fixture(autouse=True)
async def _database() -> None:
    await init_models()


def _stub_cloud_list(monkeypatch, items=CLOUD_ITEMS) -> None:
    """替换降级链执行：list_voices 返回固定云端数据，其余调用不受影响"""
    original = registry.run_with_fallback

    async def fake(kind, chain, fn_name, *args, **kwargs):
        if fn_name == "list_voices":
            return items, "hifly-voice"
        return await original(kind, chain, fn_name, *args, **kwargs)

    monkeypatch.setattr(registry, "run_with_fallback", fake)


async def _login_headers(client, fingerprint: str) -> dict[str, str]:
    tokens = await code_login(client, await create_unused_code(), fingerprint=fingerprint)
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


async def test_cloud_list_marks_imported_and_hides_other_users(client, monkeypatch) -> None:
    _stub_cloud_list(monkeypatch)
    headers = await _login_headers(client, "fp-cloud-list.abcd1234")

    # 初始：两条云端声音均可导入
    r = await client.get("/api/v1/voices/cloud", headers=headers)
    assert r.status_code == 200, r.text
    items = r.json()
    assert [i["cloudId"] for i in items] == ["cloud-voice-aaa", "cloud-voice-bbb"]
    assert all(i["imported"] is False and i["localVoiceId"] is None for i in items)

    # aaa 被其他用户认领 → 对当前用户隐藏；bbb 本人已导入 → imported=True
    me = await client.get("/api/v1/auth/me", headers=headers)
    my_user_id = me.json()["id"]
    async with SessionLocal() as db:
        db.add(Voice(user_id="other-user", name="他人声音", provider_voice_id="cloud-voice-aaa", status="ready"))
        db.add(Voice(user_id=my_user_id, name="我的声音", provider_voice_id="cloud-voice-bbb", status="ready"))
        await db.commit()

    r = await client.get("/api/v1/voices/cloud", headers=headers)
    items = r.json()
    assert [i["cloudId"] for i in items] == ["cloud-voice-bbb"]
    assert items[0]["imported"] is True and items[0]["localVoiceId"]


async def test_cloud_import_creates_ready_voice_without_reclone(client, monkeypatch) -> None:
    _stub_cloud_list(monkeypatch, _cloud_items("cloud-imp"))
    headers = await _login_headers(client, "fp-cloud-import.abcd1234")

    r = await client.post(
        "/api/v1/voices/cloud/import",
        json={"cloudId": "cloud-imp-aaa", "consentToken": "consent-ok"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    voice = r.json()
    assert voice["status"] == "ready"
    assert voice["source"] == "import"
    assert voice["name"] == "裴火荣"  # 缺省用云端名称
    assert voice["rate"] == "1.1" and voice["pitch"] == "0.9"  # 云端参数随导入落库

    # 导入后出现在"我的声音"，可直接用于 TTS（status=ready）
    listed = (await client.get("/api/v1/voices", headers=headers)).json()
    assert any(v["id"] == voice["id"] and v["status"] == "ready" for v in listed)

    # 重复导入 → 409
    r = await client.post(
        "/api/v1/voices/cloud/import",
        json={"cloudId": "cloud-imp-aaa", "consentToken": "consent-ok"},
        headers=headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ALREADY_IMPORTED"


async def test_cloud_import_rejects_unknown_id_and_missing_consent(client, monkeypatch) -> None:
    _stub_cloud_list(monkeypatch, _cloud_items("cloud-guard"))
    headers = await _login_headers(client, "fp-cloud-guard.abcd1234")

    # 云端不存在的 ID：防任意 ID 注入
    r = await client.post(
        "/api/v1/voices/cloud/import",
        json={"cloudId": "not-in-cloud", "consentToken": "consent-ok"},
        headers=headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CLOUD_VOICE_NOT_FOUND"

    # 合规红线：缺失授权凭证直接拒绝
    r = await client.post(
        "/api/v1/voices/cloud/import",
        json={"cloudId": "cloud-guard-aaa", "consentToken": ""},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "CONSENT_REQUIRED"


async def test_cloud_import_custom_name_overrides_cloud_title(client, monkeypatch) -> None:
    _stub_cloud_list(monkeypatch, _cloud_items("cloud-name"))
    headers = await _login_headers(client, "fp-cloud-name.abcd1234")

    r = await client.post(
        "/api/v1/voices/cloud/import",
        json={"cloudId": "cloud-name-bbb", "name": "找回 · 主账号声音", "consentToken": "consent-ok"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "找回 · 主账号声音"


async def test_cloud_list_hides_in_flight_clone_and_blocks_race_import(client, monkeypatch) -> None:
    """克隆竞态窗口：供应商已训完但本地尚未回填 provider_voice_id，按名称隐藏且拒绝抢先导入"""
    items = [{"voice": "cloud-race-aaa", "type": 8, "title": "竞态中声音", "rate": "1.0"}]
    _stub_cloud_list(monkeypatch, items)
    headers = await _login_headers(client, "fp-cloud-race.abcd1234")

    async with SessionLocal() as db:
        db.add(Voice(user_id="other-user", name="竞态中声音", provider_voice_id="", status="training"))
        await db.commit()

    r = await client.get("/api/v1/voices/cloud", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == []  # 名称命中克隆中记录 → 不进找回池

    r = await client.post(
        "/api/v1/voices/cloud/import",
        json={"cloudId": "cloud-race-aaa", "consentToken": "consent-ok"},
        headers=headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CLONE_IN_PROGRESS"


async def test_cloud_import_revives_own_rejected_record(client, monkeypatch) -> None:
    """本人 rejected 记录不死锁找回：列表标记可导入，导入即复活为 ready"""
    _stub_cloud_list(monkeypatch, _cloud_items("cloud-rev"))
    headers = await _login_headers(client, "fp-cloud-revive.abcd1234")

    me = await client.get("/api/v1/auth/me", headers=headers)
    my_user_id = me.json()["id"]
    async with SessionLocal() as db:
        rejected = Voice(user_id=my_user_id, name="被否的声音", provider_voice_id="cloud-rev-aaa", status="rejected")
        db.add(rejected)
        await db.commit()
        rejected_id = rejected.id

    r = await client.get("/api/v1/voices/cloud", headers=headers)
    item = next(i for i in r.json() if i["cloudId"] == "cloud-rev-aaa")
    assert item["imported"] is False and item["localVoiceId"] == rejected_id

    r = await client.post(
        "/api/v1/voices/cloud/import",
        json={"cloudId": "cloud-rev-aaa", "consentToken": "consent-ok"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    voice = r.json()
    assert voice["id"] == rejected_id  # 复用原记录，不新建（唯一索引约束）
    assert voice["status"] == "ready"
