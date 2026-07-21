"""ipasset HTTP 层：/personas（IP 档案 CRUD + 激活切换）"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from .schemas import PersonaIn, PersonaOut, PersonaUpdate
from .service import activate, create_persona, list_personas, update_persona

router = APIRouter(prefix="/personas", tags=["ipasset"])


@router.get("", response_model=list[PersonaOut])
async def api_list(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await list_personas(db, user_id)


@router.post("", response_model=PersonaOut)
async def api_create(body: PersonaIn, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await create_persona(db, user_id, body)


@router.put("/{persona_id}", response_model=PersonaOut)
async def api_update(
    persona_id: str,
    body: PersonaUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await update_persona(db, user_id, persona_id, body)


@router.post("/{persona_id}/activate", response_model=PersonaOut)
async def api_activate(
    persona_id: str, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)
):
    return await activate(db, user_id, persona_id)
