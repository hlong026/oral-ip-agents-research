"""publish 路由（/publish/*，F-501~F-504）"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import service
from .schemas import (
    AccountOut,
    AccountUpdateIn,
    ExportOut,
    JobOut,
    JobPageOut,
    PublishIn,
    QrcodePollOut,
    QrcodeStartOut,
)

router = APIRouter(prefix="/publish", tags=["publish"])


# ---- 账号授权 ----


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[AccountOut]:
    return await service.list_accounts(db, user_id)


@router.post("/accounts/qrcode", response_model=QrcodeStartOut)
async def qrcode_start(
    platform: str = Query(...),
    user_id: str = Depends(get_current_user_id),
) -> QrcodeStartOut:
    """发起扫码授权（F-502）"""
    return await service.qrcode_start(platform)


@router.get("/accounts/qrcode/{ticket}", response_model=QrcodePollOut)
async def qrcode_poll(
    ticket: str,
    platform: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> QrcodePollOut:
    """轮询平台扫码状态；成功后自动保存账号并返回账号信息。"""
    return await service.qrcode_poll(db, user_id, platform, ticket)


@router.post("/accounts/{account_id}/reauth", response_model=QrcodeStartOut)
async def reauth_account(
    account_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> QrcodeStartOut:
    """登录态失效 → 一键重新授权"""
    return await service.reauth_account(db, user_id, account_id)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.remove_account(db, user_id, account_id)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def rename_account(
    account_id: str,
    inp: AccountUpdateIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> AccountOut:
    """账号重命名（多账号辨识：昵称提取失败或与平台同名时手动标记）"""
    return await service.rename_account(db, user_id, account_id, inp.nickname)


# ---- 发布任务 ----


@router.post("/jobs", response_model=list[JobOut])
async def create_jobs(
    inp: PublishIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[JobOut]:
    return await service.create_jobs(db, user_id, inp)


@router.get("/jobs", response_model=JobPageOut)
async def list_jobs(
    status_: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JobPageOut:
    return await service.list_jobs(db, user_id, status_, page, page_size)


@router.get("/logs", response_model=JobPageOut)
async def publish_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JobPageOut:
    """全量发布日志（F-504 失败原因可见）"""
    return await service.list_jobs(db, user_id, None, page, page_size)


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
async def retry_job(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    return await service.retry_job(db, user_id, job_id)


@router.post("/jobs/{job_id}/export", response_model=ExportOut)
async def export_job(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ExportOut:
    """失败降级：仅导出 MP4（F-504）"""
    return await service.export_job(db, user_id, job_id)
