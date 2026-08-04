from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    content = target.read_text(encoding="utf-8")
    if content.count(old) != 1:
        raise RuntimeError(f"expected exactly one match in {path}: {old[:80]!r}")
    target.write_text(content.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str, expected: int) -> None:
    target = ROOT / path
    content = target.read_text(encoding="utf-8")
    if content.count(old) != expected:
        raise RuntimeError(
            f"expected {expected} matches in {path}, got {content.count(old)}: {old!r}"
        )
    target.write_text(content.replace(old, new), encoding="utf-8")


# Request schemas no longer hard-code a three-second ceiling. Runtime validation uses
# the actual media duration and rejects timestamps at/after EOF.
replace_all(
    "server/app/modules/pipeline/schemas.py",
    'selectedFrameMs: int = Field(default=1500, ge=0, le=3000)',
    'selectedFrameMs: int = Field(default=1500, ge=0)',
    2,
)

# Route cover operations through the duration-aware boundary and validate both draft
# persistence and finalization, so API clients cannot bypass the editor UI.
replace_once(
    "server/app/modules/pipeline/router.py",
    "from . import service\n",
    "from . import cover_timeline, service\n",
)
replace_once(
    "server/app/modules/pipeline/router.py",
    """async def put_publication_draft(
    task_id: str,
    inp: PublicationDraftPutIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PublicationRevisionOut:
    return await service.put_publication_draft(db, task_id, user_id, inp)
""",
    """async def put_publication_draft(
    task_id: str,
    inp: PublicationDraftPutIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PublicationRevisionOut:
    await cover_timeline.validate_selected_frame(
        db, task_id, user_id, inp.content.cover.selectedFrameMs
    )
    return await service.put_publication_draft(db, task_id, user_id, inp)
""",
)
replace_once(
    "server/app/modules/pipeline/router.py",
    "return await service.cover_candidates(db, task_id, user_id)",
    "return await cover_timeline.cover_candidates(db, task_id, user_id)",
)
replace_once(
    "server/app/modules/pipeline/router.py",
    "return await service.cover_preview(db, task_id, user_id, inp)",
    "return await cover_timeline.cover_preview(db, task_id, user_id, inp)",
)
replace_once(
    "server/app/modules/pipeline/router.py",
    """async def finalize_publication(
    task_id: str,
    inp: PublicationFinalizeIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PublicationRevisionOut:
    return await service.finalize_publication(db, task_id, user_id, inp)
""",
    """async def finalize_publication(
    task_id: str,
    inp: PublicationFinalizeIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PublicationRevisionOut:
    await cover_timeline.validate_latest_draft(db, task_id, user_id)
    return await service.finalize_publication(db, task_id, user_id, inp)
""",
)

cover_timeline = '''"""Duration-aware cover frame selection for the publication editor."""

import json
import math

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import exists as storage_exists
from app.core.storage import signed_media_path

from . import repository as repo
from . import service
from .schemas import CoverCandidateOut, CoverPreviewIn, CoverPreviewOut, PublicationContentIn


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
                round(
                    last_frame_ms
                    * (start_ratio + (end_ratio - start_ratio) * index / (sample_count - 1))
                ),
            ),
        )
        for index in range(sample_count)
    }
    return sorted(timestamps)


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
                "message": (
                    f"封面时间点超出视频时长，请选择 0 至 "
                    f"{max(0, duration_ms - 1) / 1000:.1f} 秒之间的位置"
                ),
            },
        )
    return duration_ms


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
'''
(ROOT / "server/app/modules/pipeline/cover_timeline.py").write_text(
    cover_timeline, encoding="utf-8"
)

backend_tests = '''"""Full-timeline cover sampling and duration boundary tests."""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.pipeline import cover_timeline
from app.modules.pipeline.schemas import CoverPreviewIn, PublicationCoverIn


def test_long_video_candidates_span_the_complete_timeline():
    timestamps = cover_timeline.candidate_timestamps(60_000)

    assert len(timestamps) == 6
    assert timestamps == sorted(set(timestamps))
    assert timestamps[0] < 5_000
    assert timestamps[-1] > 55_000
    assert all(0 <= item < 60_000 for item in timestamps)


def test_short_video_candidates_remain_in_range():
    timestamps = cover_timeline.candidate_timestamps(2_000)

    assert len(timestamps) == 3
    assert all(0 <= item < 2_000 for item in timestamps)
    assert timestamps[-1] > 1_800


def test_cover_schemas_accept_positions_after_three_seconds():
    assert PublicationCoverIn(selectedFrameMs=15_000).selectedFrameMs == 15_000
    assert CoverPreviewIn(selectedFrameMs=15_000).selectedFrameMs == 15_000


async def test_duration_validation_rejects_eof_and_accepts_last_frame(monkeypatch):
    task = SimpleNamespace(artifacts_json=json.dumps({"duration": 12.0}))

    async def fake_must_get(_db, _task_id, _user_id):
        return task

    monkeypatch.setattr(cover_timeline.service, "_must_get", fake_must_get)

    assert await cover_timeline.validate_selected_frame(None, "task-1", "user-1", 11_999) == 12_000
    with pytest.raises(HTTPException) as exc:
        await cover_timeline.validate_selected_frame(None, "task-1", "user-1", 12_000)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "COVER_FRAME_OUT_OF_RANGE"
'''
(ROOT / "server/tests/test_cover_timeline.py").write_text(backend_tests, encoding="utf-8")

# Editor: expose all server candidates and add an arbitrary full-duration range selector.
replace_once(
    "apps/web/src/pages/EditorPage.tsx",
    """  const firstThreeSeconds = (coverCandidates ?? []).filter(
    (candidate: CoverCandidate) => candidate.timestampMs <= 3000,
  );
""",
    """  const allCoverCandidates: CoverCandidate[] = coverCandidates ?? [];
  const artifactDurationMs = Math.round(
    Number(detail?.artifacts?.duration ?? 0) * 1000,
  );
  const latestCandidateMs = allCoverCandidates.reduce(
    (latest, candidate) => Math.max(latest, candidate.timestampMs),
    0,
  );
  const coverTimelineMaxMs = Math.max(
    0,
    artifactDurationMs > 0 ? artifactDurationMs - 1 : latestCandidateMs,
  );
  const selectCoverFrame = (timestampMs: number) => {
    const selectedFrameMs = Math.min(
      coverTimelineMaxMs,
      Math.max(0, Math.round(timestampMs)),
    );
    if (videoRef.current) {
      videoRef.current.currentTime = selectedFrameMs / 1000;
    }
    updateContent((current) => ({
      ...current,
      cover: { ...current.cover, selectedFrameMs },
    }));
  };
""",
)
replace_once(
    "apps/web/src/pages/EditorPage.tsx",
    """                    {coverError ? (
""",
    """                    <div className="mb-4 rounded-xl border border-stroke bg-white/[0.03] p-3">
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-text-3">
                        <span>全视频时间轴</span>
                        <span>
                          0.0s – {(coverTimelineMaxMs / 1000).toFixed(1)}s
                        </span>
                      </div>
                      <input
                        aria-label="封面时间轴"
                        type="range"
                        min={0}
                        max={coverTimelineMaxMs}
                        step={100}
                        value={Math.min(
                          coverTimelineMaxMs,
                          content.cover.selectedFrameMs,
                        )}
                        onChange={(event) =>
                          selectCoverFrame(Number(event.target.value))
                        }
                        className="w-full accent-brand-from"
                      />
                      <div className="mt-2 flex items-center justify-between gap-3">
                        <span className="text-xs text-text-3">
                          当前播放 {(currentTimeMs / 1000).toFixed(1)}s
                        </span>
                        <button
                          type="button"
                          className="btn-ghost px-3 py-1 text-xs"
                          onClick={() => selectCoverFrame(currentTimeMs)}
                        >
                          使用当前播放位置
                        </button>
                      </div>
                    </div>
                    {coverError ? (
""",
)
replace_once(
    "apps/web/src/pages/EditorPage.tsx",
    ") : firstThreeSeconds.length === 0 ? (",
    ") : allCoverCandidates.length === 0 ? (",
)
replace_once(
    "apps/web/src/pages/EditorPage.tsx",
    "{firstThreeSeconds.map((candidate) => (",
    "{allCoverCandidates.map((candidate) => (",
)
replace_once(
    "apps/web/src/pages/EditorPage.tsx",
    """                            onClick={() =>
                              updateContent((current) => ({
                                ...current,
                                cover: {
                                  ...current.cover,
                                  selectedFrameMs: candidate.timestampMs,
                                },
                              }))
                            }
""",
    """                            onClick={() =>
                              selectCoverFrame(candidate.timestampMs)
                            }
""",
)

# Frontend regression evidence: a 30-second task exposes/selects a frame well after 3s.
replace_once(
    "apps/web/src/__tests__/EditorPage.test.tsx",
    """  artifacts: {
    final_video_url: "/media/compose/v1.mp4?exp=1&sig=test",
    script: "第一句。第二句。",
  },
""",
    """  artifacts: {
    final_video_url: "/media/compose/v1.mp4?exp=1&sig=test",
    script: "第一句。第二句。",
    duration: 30,
  },
""",
)
replace_once(
    "apps/web/src/__tests__/EditorPage.test.tsx",
    """    vi.mocked(pipelineApi.coverCandidates).mockResolvedValue([
      { timestampMs: 0, imageUrl: "/covers/0.jpg" },
      { timestampMs: 1000, imageUrl: "/covers/1.jpg" },
      { timestampMs: 2000, imageUrl: "/covers/2.jpg" },
      { timestampMs: 3000, imageUrl: "/covers/3.jpg" },
    ]);
""",
    """    vi.mocked(pipelineApi.coverCandidates).mockResolvedValue([
      { timestampMs: 1500, imageUrl: "/covers/1.jpg" },
      { timestampMs: 6900, imageUrl: "/covers/2.jpg" },
      { timestampMs: 12300, imageUrl: "/covers/3.jpg" },
      { timestampMs: 17700, imageUrl: "/covers/4.jpg" },
      { timestampMs: 23100, imageUrl: "/covers/5.jpg" },
      { timestampMs: 28500, imageUrl: "/covers/6.jpg" },
    ]);
""",
)
replace_once(
    "apps/web/src/__tests__/EditorPage.test.tsx",
    'await user.click(screen.getByRole("button", { name: /选择 2\\.0s 封面/ }));',
    'await user.click(screen.getByRole("button", { name: /选择 17\\.7s 封面/ }));',
)
replace_once(
    "apps/web/src/__tests__/EditorPage.test.tsx",
    "selectedFrameMs: 2000,",
    "selectedFrameMs: 17700,",
)
replace_once(
    "apps/web/src/__tests__/EditorPage.test.tsx",
    """  it("合成前先保存草稿、报价并调用 finalize", async () => {
""",
    """  it("全视频时间轴可直接选择三秒后的任意位置", async () => {
    renderEditor();

    const timeline = await screen.findByLabelText("封面时间轴");
    fireEvent.change(timeline, { target: { value: "20000" } });
    await vi.advanceTimersByTimeAsync(750);

    await waitFor(() => {
      expect(pipelineApi.savePublicationDraft).toHaveBeenLastCalledWith(
        task.id,
        expect.objectContaining({
          content: expect.objectContaining({
            cover: expect.objectContaining({ selectedFrameMs: 20000 }),
          }),
        }),
      );
    });
  });

  it("合成前先保存草稿、报价并调用 finalize", async () => {
""",
)

# Remove the temporary self-application machinery from the resulting branch.
workflow_path = ROOT / ".github/workflows/ci.yml"
workflow = workflow_path.read_text(encoding="utf-8")
workflow = workflow.replace("permissions:\n  contents: write\n\n", "", 1)
temp_step = '''      - name: 临时应用封面全时间轴补丁
        if: github.event_name == 'pull_request' && github.head_ref == 'fix/cover-full-timeline-p0'
        env:
          HEAD_REF: ${{ github.head_ref }}
        run: |
          git fetch origin "$HEAD_REF"
          git checkout -B "$HEAD_REF" "origin/$HEAD_REF"
          python scripts/apply_cover_timeline_patch.py
          uv run --directory server ruff format app/modules/pipeline/cover_timeline.py app/modules/pipeline/router.py app/modules/pipeline/schemas.py tests/test_cover_timeline.py
          pnpm exec prettier --write apps/web/src/pages/EditorPage.tsx apps/web/src/__tests__/EditorPage.test.tsx
          APP_ENV=test DATABASE_URL=sqlite+aiosqlite:///./ci_cover_openapi.db IM_ENABLED=true DOUYIN_IM_APP_KEY=test-openapi-app-key uv run --directory server uvicorn app.main:app --host 127.0.0.1 --port 8000 &
          backend_pid=$!
          trap 'kill "$backend_pid"' EXIT
          for i in $(seq 1 30); do
            curl -sf http://127.0.0.1:8000/healthz && break || sleep 1
          done
          node scripts/gen-api-types.mjs
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          git commit -m "fix(cover): support full timeline frame selection"
          git push origin "HEAD:$HEAD_REF"
'''
if workflow.count(temp_step) != 1:
    raise RuntimeError("temporary workflow step not found exactly once")
workflow_path.write_text(workflow.replace(temp_step, "", 1), encoding="utf-8")

Path(__file__).unlink()
