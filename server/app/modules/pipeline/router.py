"""pipeline 路由（/pipelines，F-405/406）"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import service
from .schemas import CreatePipelineIn, StatsOut, TaskOut, TaskPageOut

router = APIRouter(prefix="/pipelines", tags=["pipeline"])


class OverrideIn(BaseModel):
    artifacts: dict[str, str]


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


@router.post("/{task_id}/steps/{step}/retry", response_model=TaskOut)
async def retry_step(
    task_id: str,
    step: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    """单步重跑（F-405）"""
    return await service.retry_step(db, task_id, step, user_id)


@router.post("/{task_id}/steps/{step}/override", response_model=TaskOut)
async def override_step(
    task_id: str,
    step: str,
    inp: OverrideIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    """人工覆盖产物，从下一步续跑（F-405）"""
    return await service.override_step(db, task_id, step, user_id, inp.artifacts)


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
