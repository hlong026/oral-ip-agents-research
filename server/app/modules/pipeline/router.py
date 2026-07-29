"""pipeline 路由（/pipelines，F-405/406）"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import service
from .schemas import (
    CoverCandidateOut,
    CreatePipelineIn,
    MetadataSuggestionsOut,
    PublicationDraftPutIn,
    PublicationFinalizeIn,
    PublicationRevisionOut,
    RecomposeIn,
    RenderVersionOut,
    RetryStepIn,
    StatsOut,
    TaskOut,
    TaskPageOut,
)

router = APIRouter(prefix="/pipelines", tags=["pipeline"])


@router.post("", response_model=list[TaskOut])
async def create_pipeline(
    inp: CreatePipelineIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    """创建流水线任务（count>1 批量扇出）"""
    return await service.create(db, user_id, inp)


@router.get("", response_model=TaskPageOut)
async def list_pipelines(
    status_: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TaskPageOut:
    return await service.list_tasks(db, user_id, status_, page, page_size)


@router.get("/stats", response_model=StatsOut)
async def pipeline_stats(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> StatsOut:
    return await service.stats(db, user_id)


@router.get("/{task_id}", response_model=TaskOut)
async def get_pipeline(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    return await service.get_task(db, task_id, user_id)


@router.get("/{task_id}/renders", response_model=list[RenderVersionOut])
async def list_render_versions(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[RenderVersionOut]:
    return await service.list_render_versions(db, task_id, user_id)


@router.get("/{task_id}/publication-draft", response_model=PublicationRevisionOut)
async def get_publication_draft(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PublicationRevisionOut:
    return await service.get_publication_draft(db, task_id, user_id)


@router.put("/{task_id}/publication-draft", response_model=PublicationRevisionOut)
async def put_publication_draft(
    task_id: str,
    inp: PublicationDraftPutIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PublicationRevisionOut:
    return await service.put_publication_draft(db, task_id, user_id, inp)


@router.post("/{task_id}/metadata-suggestions", response_model=MetadataSuggestionsOut)
async def metadata_suggestions(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> MetadataSuggestionsOut:
    return await service.metadata_suggestions(db, task_id, user_id)


@router.get("/{task_id}/cover-candidates", response_model=list[CoverCandidateOut])
async def cover_candidates(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[CoverCandidateOut]:
    return await service.cover_candidates(db, task_id, user_id)


@router.post("/{task_id}/finalize", response_model=PublicationRevisionOut)
async def finalize_publication(
    task_id: str,
    inp: PublicationFinalizeIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PublicationRevisionOut:
    return await service.finalize_publication(db, task_id, user_id, inp)


@router.get("/{task_id}/publication-revisions", response_model=list[PublicationRevisionOut])
async def list_publication_revisions(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[PublicationRevisionOut]:
    return await service.list_publication_revisions(db, task_id, user_id)


@router.post("/{task_id}/recompose", response_model=RenderVersionOut)
async def recompose(
    task_id: str,
    inp: RecomposeIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> RenderVersionOut:
    return await service.recompose(db, task_id, user_id, inp)


@router.post("/{task_id}/renders/{render_id}/cancel", response_model=RenderVersionOut)
async def cancel_render(
    task_id: str,
    render_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> RenderVersionOut:
    return await service.cancel_render(db, task_id, render_id, user_id)


@router.post("/{task_id}/retry-quote")
async def retry_quote(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await service.create_retry_quote(db, task_id, user_id)


@router.post("/{task_id}/steps/{step}/retry", response_model=TaskOut)
async def retry_step(
    task_id: str,
    step: str,
    inp: RetryStepIn | None = None,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    """单步重跑（F-405）"""
    return await service.retry_step(db, task_id, step, user_id, inp.quoteId if inp else None)


@router.post("/{task_id}/confirm", response_model=TaskOut)
async def confirm_step(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    """manual 模式逐步确认"""
    return await service.confirm(db, task_id, user_id)


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_pipeline(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    return await service.cancel(db, task_id, user_id)
