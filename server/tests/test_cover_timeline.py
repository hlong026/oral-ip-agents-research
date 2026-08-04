"""Full-timeline cover sampling and duration boundary tests."""

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
