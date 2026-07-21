"""DouYin_Spider 私信协议适配回归测试。"""

import hashlib
import json

import pytest

from app.providers.im.douyin_browser import normalize_browser_snapshot
from app.providers.im.douyin_im import (
    DouyinIMConnection,
    DouyinIMProvider,
    compute_access_key,
    normalize_douyin_session,
)
from app.providers.im.proto import Live_pb2, Response_pb2


def test_normalize_playwright_storage_state_for_im() -> None:
    session = {
        "cookies": [
            {"name": "sessionid", "value": "session-value", "domain": ".douyin.com", "path": "/"},
            {"name": "s_v_web_id", "value": "verify-value", "domain": "www.douyin.com", "path": "/"},
            {"name": "ignored", "value": "other", "domain": ".example.com", "path": "/"},
        ],
        "origins": [
            {
                "origin": "https://www.douyin.com",
                "localStorage": [{"name": "oral_im_device_id", "value": "1234567890123456789"}],
            }
        ],
    }

    normalized = normalize_douyin_session(session)

    assert normalized["sessionid"] == "session-value"
    assert "sessionid=session-value" in normalized["cookie_str"]
    assert "s_v_web_id=verify-value" in normalized["cookie_str"]
    assert "ignored=other" not in normalized["cookie_str"]
    assert normalized["device_id"] == "1234567890123456789"


def test_normalize_douyin_session_requires_login_cookie() -> None:
    with pytest.raises(ValueError, match="sessionid"):
        normalize_douyin_session({"cookies": []})


def test_access_key_matches_douyin_spider_formula() -> None:
    app_key = "e1bd35ec9db7b8d846de66ed140b1ad9"
    suffix = "f8a69f1719916z"
    device_id = "1234567890123456789"

    expected = hashlib.md5(f"9{app_key}{device_id}{suffix}".encode()).hexdigest()

    assert compute_access_key(device_id, app_key=app_key, fpid="9", suffix=suffix) == expected


def test_decode_real_protobuf_private_message() -> None:
    response = Response_pb2.Response(cmd=500)
    message = response.body.new_message_notify.message
    message.sender = 123456789
    message.message_type = 7
    message.conversation_id = "0:1:owner:sender"
    message.conversation_short_id = 987654321
    message.server_message_id = 1122334455
    message.index_in_conversation = 42
    message.content = json.dumps({"text": "真实私信"}, ensure_ascii=False)

    frame = Live_pb2.PushFrame(payloadType="pb", payload=response.SerializeToString())
    connection = DouyinIMConnection({"sessionid": "session-value", "cookie_str": "sessionid=session-value"})

    decoded = connection._decode_frame(frame.SerializeToString())

    assert decoded == {
        "remote_uid": "123456789",
        "remote_nickname": "",
        "remote_avatar": "",
        "msg_type": 7,
        "content": "真实私信",
        "dy_conversation_id": "0:1:owner:sender",
        "dy_conversation_short_id": "987654321",
        "dy_ticket": "",
        "remote_message_id": "1122334455",
        "remote_index": 42,
    }


def test_normalize_browser_snapshot_builds_stable_message_keys() -> None:
    snapshot = {
        "conversation": {
            "name": "历史用户",
            "avatar": "https://example.com/avatar.png",
            "conversationId": "browser-conversation-1",
        },
        "messages": [
            {"text": "你好", "mine": False, "time": "昨天", "index": 0},
            {"text": "收到", "mine": True, "time": "昨天", "index": 1},
        ],
    }

    first = normalize_browser_snapshot(snapshot)
    second = normalize_browser_snapshot(snapshot)

    assert first == second
    assert [message["direction"] for message in first] == ["in", "out"]
    assert first[0]["remote_nickname"] == "历史用户"
    assert first[0]["dy_conversation_id"] == "browser-conversation-1"
    assert first[0]["remote_message_id"].startswith("browser:")


@pytest.mark.asyncio
async def test_provider_delegates_history_and_send_to_browser_client() -> None:
    class BrowserClient:
        async def sync_messages(self, session: dict, limit: int) -> list[dict]:
            assert limit == 20
            return [{"remote_message_id": "history-1"}]

        async def send_message(self, session: dict, remote_uid: str, remote_nickname: str, content: str) -> bool:
            assert remote_uid == "browser:user"
            assert remote_nickname == "目标用户"
            assert content == "回复内容"
            return True

    provider = DouyinIMProvider(browser_client=BrowserClient())

    records = await provider.sync_messages({"cookies": []}, limit=20)
    sent = await provider.send_message(
        session={"cookies": []},
        conversation_id="",
        conversation_short_id="",
        ticket="",
        content="回复内容",
        remote_uid="browser:user",
        remote_nickname="目标用户",
    )

    assert records == [{"remote_message_id": "history-1"}]
    assert sent is True
