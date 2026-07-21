"""content HTTP 层：解析 / 仿写 / 去重 / 选题 / 文案资产"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_active_persona_id, get_current_user_id

from .schemas import (
    ParseIn,
    ParseOut,
    RewriteIn,
    RewriteOut,
    ScriptCreateIn,
    ScriptOut,
    SimilarityIn,
    SimilarityOut,
    TopicsIn,
    TopicsOut,
)
from .service import (
    create_script,
    get_script,
    list_scripts,
    parse_by_id,
    parse_upload,
    parse_url,
    rewrite,
    similarity,
    topics,
)

router = APIRouter(prefix="/content", tags=["content"])


@router.post("/parse", response_model=ParseOut)
async def api_parse(
    body: str | None = Form(None),
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
    user_id: str = Depends(get_current_user_id),
    persona_id: str | None = Depends(get_current_active_persona_id),
    db: AsyncSession = Depends(get_db),
):
    if file is not None:
        return await parse_upload(db, user_id, file.filename or "upload.mp4", await file.read(), persona_id)
    target = url or body
    if not target:
        # JSON 形式兼容
        return ParseOut(transcript=None, degraded=True, platform=None, title=None)
    return await parse_url(db, user_id, target, persona_id)


@router.post("/parse/json", response_model=ParseOut)
async def api_parse_json(
    body: ParseIn,
    user_id: str = Depends(get_current_user_id),
    persona_id: str | None = Depends(get_current_active_persona_id),
    db: AsyncSession = Depends(get_db),
):
    # 支持两种输入：url 或 videoId + platform
    if body.videoId and body.platform:
        return await parse_by_id(db, user_id, body.videoId, body.platform, persona_id)
    return await parse_url(db, user_id, body.url or "", persona_id)


@router.post("/rewrite", response_model=RewriteOut)
async def api_rewrite(body: RewriteIn, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await rewrite(db, user_id, body.text, body.intensity, body.prompt, body.scriptId)


@router.post("/similarity", response_model=SimilarityOut)
async def api_similarity(body: SimilarityIn, _user_id: str = Depends(get_current_user_id)):
    return await similarity(body.text)


@router.post("/topics", response_model=TopicsOut)
async def api_topics(body: TopicsIn, _user_id: str = Depends(get_current_user_id)):
    return TopicsOut(topics=await topics(body.keyword))


@router.post("/scripts", response_model=ScriptOut)
async def api_create_script(
    body: ScriptCreateIn,
    user_id: str = Depends(get_current_user_id),
    persona_id: str | None = Depends(get_current_active_persona_id),
    db: AsyncSession = Depends(get_db),
):
    return await create_script(db, user_id, persona_id, body.title, body.text, body.platform, body.topic)


@router.get("/scripts", response_model=list[ScriptOut])
async def api_scripts(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await list_scripts(db, user_id)


@router.get("/scripts/{script_id}", response_model=ScriptOut)
async def api_script(script_id: str, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await get_script(db, user_id, script_id)
