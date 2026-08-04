"""Duration-aware cover frame selection for the publication editor."""

import json
import math

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import exists as storage_exists
from app.core.storage import signed_media_path

from . import repository as repo
from . import service
from .schemas import (
    CoverCandidateOut,
    CoverPreviewIn,
    CoverPreviewOut,
    PublicationContentIn,
    PublicationRevisionOut,
)


def duration_ms_from_artifacts(artifacts: dict) -> int:
    """Return the authoritative media duration in milliseconds.

    Completed compose tasks persist duration in seconds. Legacy records without the
    field retain the previous three-second fallback, while new requests are always
    checked against the stored duration before FFmpeg is invoked.
    """
    raw = artifacts.get("duration")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = 3.0
    if not math.isfinite(seconds) or seconds <= 0:
        seconds = 3.0
    return max(1, round(seconds * 1000))


def candidate_timestamps(duration_ms: int) -> list[int]:
    """Sample the complete timeline instead of only the opening three seconds."""
    duration_ms = max(1, int(duration_ms))
    last_frame_ms = duration_ms - 1
    if last_frame_ms <= 0:
        return [0]

    sample_count = 6 if duration_ms >= 3000 else 3
    sample_count = min(sample_count, last_frame_ms + 1)
    if sample_count <= 1:
        return [0]

    start_ratio = 0.05
    end_ratio = 0.95
    timestamps = {
        min(
            last_frame_ms,
            max(
                0,
                round(last_frame_ms * (start_ratio + (end_ratio - start_ratio) * index / (sample_count - 1))),
            ),
        )
        for index in range(sample_count)
    }
    return sorted(timestamps)


def normalized_selected_frame(selected_frame_ms: int, duration_ms: int) -> int:
    """Keep valid selections and repair legacy defaults that point beyond EOF."""
    duration_ms = max(1, int(duration_ms))
    if 0 <= selected_frame_ms < duration_ms:
        return selected_frame_ms
    timestamps = candidate_timestamps(duration_ms)
    return timestamps[len(timestamps) // 2]


async def validate_selected_frame(
    db: AsyncSession,
    task_id: str,
    user_id: str,
    selected_frame_ms: int,
) -> int:
    task = await service._must_get(db, task_id, user_id)
    artifacts = json.loads(task.artifacts_json or "{}")
    duration_ms = duration_ms_from_artifacts(artifacts)
    if selected_frame_ms >= duration_ms:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "COVER_FRAME_OUT_OF_RANGE",
                "message": (f"封面时间点超出视频时长，请选择 0 至 {max(0, duration_ms - 1) / 1000:.1f} 秒之间的位置"),
            },
        )
    return duration_ms


async def get_publication_draft(
    db: AsyncSession,
    task_id: str,
    user_id: str,
) -> PublicationRevisionOut:
    """Return a draft whose selected frame is always valid for the current media."""
    draft_out = await service.get_publication_draft(db, task_id, user_id)
    task = await service._must_get(db, task_id, user_id)
    artifacts = json.loads(task.artifacts_json or "{}")
    duration_ms = duration_ms_from_artifacts(artifacts)
    selected = normalized_selected_frame(draft_out.content.cover.selectedFrameMs, duration_ms)
    if selected == draft_out.content.cover.selectedFrameMs:
        return draft_out

    draft_out.content.cover.selectedFrameMs = selected
    draft = await repo.latest_draft_publication_revision(db, task_id, user_id)
    if draft is not None:
        draft.content_spec_json = draft_out.content.model_dump_json()
        await db.commit()
    return draft_out


async def validate_latest_draft(db: AsyncSession, task_id: str, user_id: str) -> None:
    draft = await repo.latest_draft_publication_revision(db, task_id, user_id)
    if draft is None:
        return
    try:
        content = PublicationContentIn.model_validate_json(draft.content_spec_json or "{}")
    except ValueError:
        return
    await validate_selected_frame(db, task_id, user_id, content.cover.selectedFrameMs)


async def cover_candidates(
    db: AsyncSession,
    task_id: str,
    user_id: str,
) -> list[CoverCandidateOut]:
    task = await service._must_get(db, task_id, user_id)
    artifacts = json.loads(task.artifacts_json or "{}")
    timestamps = candidate_timestamps(duration_ms_from_artifacts(artifacts))
    clean_key = service._clean_master_key(artifacts)
    if not clean_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "CLEAN_MASTER_REQUIRED", "message": "无可用于提取封面的 clean 视频源"},
        )
    if not await storage_exists(clean_key):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "CLEAN_MASTER_MISSING",
                "message": "成片源文件已不存在（可能被清理），请重新生成成片后再选封面",
            },
        )

    cache = artifacts.get("cover_candidates")
    if not isinstance(cache, dict):
        cache = {}
    changed = False
    candidates: list[CoverCandidateOut] = []
    for timestamp in timestamps:
        key = str(cache.get(str(timestamp)) or "")
        if not key or not await storage_exists(key):
            key = await service._extract_cover_candidate_frame(clean_key, timestamp)
            cache[str(timestamp)] = key
            changed = True
        candidates.append(
            CoverCandidateOut(
                timestampMs=timestamp,
                imageUrl=signed_media_path(key) if key else "",
            )
        )
    if changed:
        artifacts["cover_candidates"] = cache
        task.artifacts_json = json.dumps(artifacts, ensure_ascii=False)
        await db.commit()
    return candidates


async def cover_preview(
    db: AsyncSession,
    task_id: str,
    user_id: str,
    inp: CoverPreviewIn,
) -> CoverPreviewOut:
    await validate_selected_frame(db, task_id, user_id, inp.selectedFrameMs)
    return await service.cover_preview(db, task_id, user_id, inp)
