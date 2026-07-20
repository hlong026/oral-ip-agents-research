"""ipasset 数据访问"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Persona


async def list_by_user(db: AsyncSession, user_id: str) -> list[Persona]:
    res = await db.execute(select(Persona).where(Persona.user_id == user_id).order_by(Persona.created_at))
    return list(res.scalars().all())


async def get(db: AsyncSession, persona_id: str, user_id: str) -> Persona | None:
    res = await db.execute(select(Persona).where(Persona.id == persona_id, Persona.user_id == user_id))
    return res.scalar_one_or_none()


async def create(db: AsyncSession, user_id: str, **fields) -> Persona:
    p = Persona(user_id=user_id, **fields)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def save(db: AsyncSession, persona: Persona) -> Persona:
    await db.commit()
    await db.refresh(persona)
    return persona


async def clear_active(db: AsyncSession, user_id: str) -> None:
    await db.execute(update(Persona).where(Persona.user_id == user_id).values(is_active=False))
    await db.commit()
