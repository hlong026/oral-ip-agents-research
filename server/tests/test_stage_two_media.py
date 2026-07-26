"""第二阶段真实媒体 Provider 与成片质量门禁。"""

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from app.core.db import SessionLocal, init_models
from app.core.storage import local_path, save_bytes
from app.providers.base import ComposeInput, StepRecoverableError


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

    response = await client.get(f"/media/{key.replace(' ', '%20')}")

    assert response.status_code == 200
    assert response.content == b"stored-video"
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"


async def test_media_route_serves_partial_content_for_range(client) -> None:
    key = await save_bytes("renders", "clip.mp4", b"0123456789")

    response = await client.get(f"/media/{key}", headers={"Range": "bytes=2-5"})

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"

    # 开放尾区间与后缀区间（Safari 探测常用）
    tail = await client.get(f"/media/{key}", headers={"Range": "bytes=7-"})
    assert tail.status_code == 206
    assert tail.content == b"789"
    suffix = await client.get(f"/media/{key}", headers={"Range": "bytes=-3"})
    assert suffix.status_code == 206
    assert suffix.content == b"789"


async def test_media_route_rejects_unsatisfiable_range_and_supports_head(client) -> None:
    key = await save_bytes("renders", "clip2.mp4", b"abcdef")

    bad = await client.get(f"/media/{key}", headers={"Range": "bytes=99-"})
    assert bad.status_code == 416
    assert bad.headers["content-range"] == "bytes */6"

    head = await client.head(f"/media/{key}")
    assert head.status_code == 200
    assert head.headers["content-length"] == "6"
    assert head.headers["accept-ranges"] == "bytes"
    assert head.content == b""


async def test_media_route_ignores_unsupported_range_forms(client) -> None:
    key = await save_bytes("renders", "clip3.mp4", b"abcdef")

    # 多区间与未知单位按 RFC 9110 忽略，回落 200 全量
    multi = await client.get(f"/media/{key}", headers={"Range": "bytes=0-1,4-5"})
    assert multi.status_code == 200
    assert multi.content == b"abcdef"
    unknown = await client.get(f"/media/{key}", headers={"Range": "items=0-2"})
    assert unknown.status_code == 200


async def test_media_route_serves_empty_file_without_streaming(client) -> None:
    key = await save_bytes("renders", "empty.mp4", b"")

    response = await client.get(f"/media/{key}")

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == "0"


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
