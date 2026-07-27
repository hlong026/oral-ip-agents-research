"""第二阶段真实媒体 Provider 与成片质量门禁。"""

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile

from app.core.db import SessionLocal, init_models
from app.core.storage import local_path, save_bytes, signed_media_path
from app.providers.base import ComposeInput, StepRecoverableError
from tests.helpers import code_login, create_unused_code


@pytest_asyncio.fixture(autouse=True)
async def _database() -> None:
    await init_models()


async def test_tts_rejects_missing_provider_task_id(monkeypatch) -> None:
    from app.providers.hifly import HiFlyVoice

    class FakeClient:
        async def request(self, *_args, **_kwargs):
            return {}

    provider = HiFlyVoice()
    provider._c = FakeClient()

    with pytest.raises(StepRecoverableError, match="task_id"):
        await provider.synthesize("voice-id", "真实口播文案")


def test_invalid_media_key_signature_is_rejected_without_exception() -> None:
    from app.core.storage import verify_media_signature

    assert verify_media_signature("../private.txt", "9999999999", "invalid") is False


async def test_avatar_image_bomb_is_rejected_as_invalid_image(monkeypatch) -> None:
    from PIL import Image

    from app.modules.avatar.router import _read_valid_image

    def bomb(*_args, **_kwargs):
        raise Image.DecompressionBombError("too many pixels")

    monkeypatch.setattr(Image, "open", bomb)
    upload = UploadFile(filename="bomb.png", file=BytesIO(b"compressed-image"))

    with pytest.raises(HTTPException) as error:
        await _read_valid_image(upload)

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "INVALID_IMAGE"


async def test_avatar_rejects_success_without_video_url(monkeypatch) -> None:
    from app.providers.hifly import HiFlyAvatar

    provider = HiFlyAvatar()

    async def completed_without_video(_task_id: str):
        return {"status": 3, "video_url": "", "duration": 10}

    monkeypatch.setattr(provider, "query_video_task", completed_without_video)

    with pytest.raises(StepRecoverableError, match="视频地址"):
        await provider.poll_video_task("render-task")


async def test_ffmpeg_compose_creates_quality_checked_mp4(tmp_path: Path) -> None:
    from app.providers.real import FFmpegCompose

    source = tmp_path / "source.mp4"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=360x640:d=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
        str(source),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert await process.wait() == 0
    source_key = await save_bytes("stage-two", "source.mp4", source.read_bytes())

    result = await FFmpegCompose().compose(
        ComposeInput(
            video_key=source_key,
            audio_key=None,
            subtitle_words=[],
            subtitle_style={},
            bgm_key=None,
            bgm_mode="off",
            cover_text="真实成片",
        )
    )

    assert result.video_key.endswith(".mp4")
    assert result.cover_key.endswith(".jpg")
    assert local_path(result.video_key).stat().st_size > 1_000
    assert result.quality["passed"] is True
    assert result.quality["videoCodec"] == "h264"
    assert result.quality["audioCodec"] == "aac"
    assert (result.quality["width"], result.quality["height"]) == (1080, 1920)


async def test_corrupt_video_fails_quality_gate() -> None:
    from app.providers.media_quality import MediaQualityError, inspect_media

    corrupt_key = await save_bytes("stage-two", "corrupt.mp4", b"not-a-video")

    with pytest.raises(MediaQualityError):
        await inspect_media(corrupt_key, require_audio=True)


async def test_s3_media_is_materialized_before_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    from app.providers import media_quality, real

    async def remote_bytes(_key: str) -> bytes:
        return b"remote-media"

    monkeypatch.setattr(real.settings, "storage_driver", "s3")
    monkeypatch.setattr(media_quality.settings, "storage_driver", "s3")
    monkeypatch.setattr(real, "read_bytes", remote_bytes)
    monkeypatch.setattr(media_quality, "read_bytes", remote_bytes)

    compose_path = await real._materialize("remote/video.mp4", tmp_path, "video")
    probe_path = await media_quality._materialize("remote/video.mp4", tmp_path)

    assert await asyncio.to_thread(compose_path.read_bytes) == b"remote-media"
    assert await asyncio.to_thread(Path(probe_path).read_bytes) == b"remote-media"


async def test_media_route_reads_from_active_storage_driver(client) -> None:
    key = await save_bytes("renders", "final video.mp4", b"stored-video")

    unsigned = await client.get(f"/media/{key.replace(' ', '%20')}")
    response = await client.get(signed_media_path(key))

    assert unsigned.status_code == 403
    assert response.status_code == 200
    assert response.content == b"stored-video"
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"


async def test_media_route_serves_partial_content_for_range(client) -> None:
    key = await save_bytes("renders", "clip.mp4", b"0123456789")

    media_url = signed_media_path(key)
    response = await client.get(media_url, headers={"Range": "bytes=2-5"})

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"

    # 开放尾区间与后缀区间（Safari 探测常用）
    tail = await client.get(media_url, headers={"Range": "bytes=7-"})
    assert tail.status_code == 206
    assert tail.content == b"789"
    suffix = await client.get(media_url, headers={"Range": "bytes=-3"})
    assert suffix.status_code == 206
    assert suffix.content == b"789"


async def test_media_route_rejects_unsatisfiable_range_and_supports_head(client) -> None:
    key = await save_bytes("renders", "clip2.mp4", b"abcdef")

    media_url = signed_media_path(key)
    bad = await client.get(media_url, headers={"Range": "bytes=99-"})
    assert bad.status_code == 416
    assert bad.headers["content-range"] == "bytes */6"

    head = await client.head(media_url)
    assert head.status_code == 200
    assert head.headers["content-length"] == "6"
    assert head.headers["accept-ranges"] == "bytes"
    assert head.content == b""


async def test_media_route_ignores_unsupported_range_forms(client) -> None:
    key = await save_bytes("renders", "clip3.mp4", b"abcdef")

    # 多区间与未知单位按 RFC 9110 忽略，回落 200 全量
    media_url = signed_media_path(key)
    multi = await client.get(media_url, headers={"Range": "bytes=0-1,4-5"})
    assert multi.status_code == 200
    assert multi.content == b"abcdef"
    unknown = await client.get(media_url, headers={"Range": "items=0-2"})
    assert unknown.status_code == 200


async def test_media_route_serves_empty_file_without_streaming(client) -> None:
    key = await save_bytes("renders", "empty.mp4", b"")

    response = await client.get(signed_media_path(key))

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == "0"


async def test_media_route_rejects_expired_and_tampered_signatures(client) -> None:
    key = await save_bytes("renders", "signed.mp4", b"signed")

    expired = await client.get(signed_media_path(key, expires_in=-1))
    valid = signed_media_path(key)
    tampered = await client.get(valid.replace("/media/renders/", "/media/other/"))

    assert expired.status_code == 403
    assert tampered.status_code == 403


async def test_stream_upload_stops_after_limit_plus_one_byte() -> None:
    from app.core.storage import UploadTooLarge, save_stream

    class OversizedStream:
        remaining = 32
        requested: list[int] = []

        async def read(self, size: int = -1) -> bytes:
            self.requested.append(size)
            if self.remaining <= 0:
                return b""
            count = min(size, self.remaining)
            self.remaining -= count
            return b"x" * count

    source = OversizedStream()
    with pytest.raises(UploadTooLarge):
        await save_stream("stream-tests", "large.bin", source, max_bytes=4, chunk_size=2)

    assert sum(source.requested) <= 5


async def test_upload_routes_reject_fake_media_with_valid_extensions(client) -> None:
    tokens = await code_login(client, await create_unused_code(), fingerprint="fp-media-type.abcd1234")
    headers = {"Authorization": f"Bearer {tokens['accessToken']}"}

    voice = await client.post(
        "/api/v1/voices/clone",
        data={"name": "伪音频", "consentToken": "consent-ok"},
        files={"file": ("fake.wav", b"not-audio", "audio/wav")},
        headers=headers,
    )
    image = await client.post(
        "/api/v1/avatars/create-by-image",
        data={"name": "伪图片", "consentToken": "consent-ok"},
        files={"file": ("fake.png", b"not-an-image", "image/png")},
        headers=headers,
    )
    video = await client.post(
        "/api/v1/avatars/clone",
        data={"name": "伪视频", "consentToken": "consent-ok"},
        files={"file": ("fake.mp4", b"not-a-video", "video/mp4")},
        headers=headers,
    )
    content = await client.post(
        "/api/v1/content/parse",
        files={"file": ("fake.mp4", b"not-a-video", "video/mp4")},
        headers=headers,
    )

    assert voice.status_code == 422
    assert voice.json()["detail"]["code"] == "INVALID_AUDIO"
    assert image.status_code == 422
    assert image.json()["detail"]["code"] == "INVALID_IMAGE"
    assert video.status_code == 422
    assert video.json()["detail"]["code"] == "INVALID_VIDEO"
    assert content.status_code == 422
    assert content.json()["detail"]["code"] == "INVALID_MEDIA"


async def test_avatar_clone_persists_consent_evidence_without_plaintext(monkeypatch) -> None:
    from app.modules.avatar import repository as avatar_repo
    from app.modules.avatar import service as avatar_service

    async def accepted(*_args, **_kwargs):
        return "provider-task", "real-avatar"

    monkeypatch.setattr(avatar_service.registry, "run_with_fallback", accepted)

    async with SessionLocal() as db:
        created = await avatar_service.clone_avatar_by_video(
            db,
            "consent-user",
            "本人形象",
            "consent-token-plain",
            "uploads/avatar.mp4",
        )
        avatar = await avatar_repo.get(db, created.id, "consent-user")

    assert avatar is not None
    assert avatar.consent_hash
    assert avatar.consent_hash != "consent-token-plain"
    assert avatar.consented_at is not None


async def test_voice_clone_persists_unknown_submission_for_reconciliation(monkeypatch) -> None:
    from app.modules.voice import repository as voice_repo
    from app.modules.voice import service as voice_service
    from app.providers.base import ProviderOutcomeUnknown

    async def outcome_unknown(*_args, **_kwargs):
        raise ProviderOutcomeUnknown("结果未知")

    monkeypatch.setattr(voice_service.registry, "run_with_fallback", outcome_unknown)

    async with SessionLocal() as db:
        created = await voice_service.clone_voice(
            db,
            "unknown-voice-user",
            "待对账声音",
            "consent-token",
            "uploads/voice.wav",
        )
        voice = await voice_repo.get(db, created.id, "unknown-voice-user")

    assert voice is not None
    assert voice.status == "reconciliation_required"
    assert voice.provider_task_id == ""


async def test_avatar_clone_persists_unknown_submission_for_reconciliation(monkeypatch) -> None:
    from app.modules.avatar import repository as avatar_repo
    from app.modules.avatar import service as avatar_service
    from app.providers.base import ProviderOutcomeUnknown

    async def outcome_unknown(*_args, **_kwargs):
        raise ProviderOutcomeUnknown("结果未知")

    monkeypatch.setattr(avatar_service.registry, "run_with_fallback", outcome_unknown)

    async with SessionLocal() as db:
        created = await avatar_service.clone_avatar_by_image(
            db,
            "unknown-avatar-user",
            "待对账数字人",
            "consent-token",
            "uploads/avatar.png",
        )
        avatar = await avatar_repo.get(db, created.id, "unknown-avatar-user")

    assert avatar is not None
    assert avatar.status == "reconciliation_required"
    assert avatar.provider_task_id == ""


async def test_startup_marks_interrupted_asset_submissions_for_reconciliation() -> None:
    from app.modules.avatar.models import Avatar
    from app.modules.avatar.service import recover_unknown_submissions as recover_avatars
    from app.modules.voice.models import Voice
    from app.modules.voice.service import recover_unknown_submissions as recover_voices

    async with SessionLocal() as db:
        voice = Voice(user_id="startup-user", name="中断声音", status="submitting")
        avatar = Avatar(user_id="startup-user", name="中断数字人", status="submitting")
        db.add_all([voice, avatar])
        await db.commit()
        voice_id = voice.id
        avatar_id = avatar.id

        assert await recover_voices(db) == 1
        assert await recover_avatars(db) == 1

        await db.refresh(voice)
        await db.refresh(avatar)

    assert voice.id == voice_id and voice.status == "reconciliation_required"
    assert avatar.id == avatar_id and avatar.status == "reconciliation_required"
