"""S3-02 fixed Douyin IM protobuf contract."""

import base64
import hashlib
from pathlib import Path

from app.providers.im.douyin_im import DouyinIMConnection
from app.providers.im.proto.v1 import PROTOCOL_VERSION, live_pb2

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "douyin_im" / "redacted_push_v1.pb.b64"
FIXTURE_SHA256 = "af86dc364302168958eae5758cdc746c47628468203dbc41de262e118c632401"


def _fixed_frame() -> bytes:
    raw = base64.b64decode(FIXTURE_PATH.read_text(encoding="ascii").strip(), validate=True)
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    return raw


def test_decodes_versioned_redacted_push_frame() -> None:
    connection = DouyinIMConnection({"sessionid": "redacted", "cookie_str": "sessionid=redacted"})

    decoded = connection._decode_frame(_fixed_frame())

    assert PROTOCOL_VERSION == "douyin-im-push-v1"
    assert decoded == {
        "remote_uid": "202607210003",
        "remote_nickname": "",
        "remote_avatar": "",
        "msg_type": 7,
        "content": "授权协议测试消息",
        "dy_conversation_id": "0:1:redacted-owner:redacted-sender",
        "dy_conversation_short_id": "202607210002",
        "dy_ticket": "",
        "remote_message_id": "202607210001",
        "remote_index": 42,
    }


def test_rejects_frame_outside_v1_protobuf_contract() -> None:
    frame = live_pb2.PushFrame(payloadType="json", payload=b"{}")  # type: ignore[attr-defined]
    connection = DouyinIMConnection({"sessionid": "redacted", "cookie_str": "sessionid=redacted"})

    assert connection._decode_frame(frame.SerializeToString()) is None
