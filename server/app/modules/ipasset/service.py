"""ipasset 业务编排（F-701 人设引擎：字段注入生成链路）"""

import json

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from . import repository as repo
from .models import Persona
from .schemas import PersonaIn, PersonaOut, PersonaUpdate

GRADS = [
    "linear-gradient(135deg,#F59E0B,#EF4444)",
    "linear-gradient(135deg,#22D3EE,#34D399)",
    "linear-gradient(135deg,#8B5CF6,#EC4899)",
    "linear-gradient(135deg,#6366F1,#22D3EE)",
]


async def get_active_persona_id(db: AsyncSession, user_id: str) -> str | None:
    items = await repo.list_by_user(db, user_id)
    active = next((p for p in items if p.is_active), None)
    return (active or (items[0] if items else None) or Persona(id="")).id or None


async def get_active_persona_context(db: AsyncSession, user_id: str) -> str | None:
    """Return the current user's prompt context through the IpAsset service boundary."""
    persona_id = await get_active_persona_id(db, user_id)
    if persona_id is None:
        return None
    persona = await repo.get(db, persona_id, user_id)
    return persona_prompt_context(persona) if persona is not None else None


async def create_default_persona(db: AsyncSession, user_id: str, nickname: str) -> Persona:
    p = await repo.create(
        db,
        user_id,
        name=f"{nickname}的 IP",
        domain="知识科普",
        tone="专业、接地气",
        values="",
        taboo_words="[]",
        avatar_char=(nickname or "口")[0],
        avatar_grad=GRADS[0],
        is_active=True,
    )
    return p


async def list_personas(db: AsyncSession, user_id: str) -> list[PersonaOut]:
    items = await repo.list_by_user(db, user_id)
    return [to_out(p) for p in items]


async def create_persona(db: AsyncSession, user_id: str, body: PersonaIn) -> PersonaOut:
    items = await repo.list_by_user(db, user_id)
    p = await repo.create(
        db,
        user_id,
        name=body.name,
        domain=body.domain,
        tone=body.tone,
        values=body.values,
        taboo_words=json.dumps(body.tabooWords, ensure_ascii=False),
        avatar_char=body.name[0],
        avatar_grad=GRADS[len(items) % len(GRADS)],
        is_active=len(items) == 0,
        audience=body.audience,
        content_pillars=json.dumps(body.contentPillars, ensure_ascii=False),
        style_samples=body.styleSamples,
        catchphrase=body.catchphrase,
        video_duration=body.videoDuration,
        cta_style=body.ctaStyle,
        avoid_topics=json.dumps(body.avoidTopics, ensure_ascii=False),
    )
    return to_out(p)


async def update_persona(db: AsyncSession, user_id: str, persona_id: str, body: PersonaUpdate) -> PersonaOut:
    p = await repo.get(db, persona_id, user_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "IP 档案不存在"})
    if body.name is not None:
        p.name = body.name
        p.avatar_char = body.name[0]
    if body.domain is not None:
        p.domain = body.domain
    if body.tone is not None:
        p.tone = body.tone
    if body.values is not None:
        p.values = body.values
    if body.tabooWords is not None:
        p.taboo_words = json.dumps(body.tabooWords, ensure_ascii=False)
    if body.voiceId is not None:
        p.voice_id = body.voiceId or None
    if body.avatarId is not None:
        p.avatar_id = body.avatarId or None
    if body.audience is not None:
        p.audience = body.audience
    if body.contentPillars is not None:
        p.content_pillars = json.dumps(body.contentPillars, ensure_ascii=False)
    if body.styleSamples is not None:
        p.style_samples = body.styleSamples
    if body.catchphrase is not None:
        p.catchphrase = body.catchphrase
    if body.videoDuration is not None:
        p.video_duration = body.videoDuration
    if body.ctaStyle is not None:
        p.cta_style = body.ctaStyle
    if body.avoidTopics is not None:
        p.avoid_topics = json.dumps(body.avoidTopics, ensure_ascii=False)
    return to_out(await repo.save(db, p))


async def activate(db: AsyncSession, user_id: str, persona_id: str) -> PersonaOut:
    p = await repo.get(db, persona_id, user_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "IP 档案不存在"})
    await repo.clear_active(db, user_id)
    p.is_active = True
    return to_out(await repo.save(db, p))


def persona_prompt_context(p: Persona) -> str:
    """人设引擎注入：结构化多段prompt（三阶段仿写引擎核心上下文）"""
    taboo = "、".join(json.loads(p.taboo_words or "[]"))
    pillars = "、".join(json.loads(p.content_pillars or "[]"))
    avoid = "、".join(json.loads(p.avoid_topics or "[]"))

    parts = [
        f"【人设】你是「{p.name}」，领域：{p.domain}，口吻：{p.tone}。",
    ]
    if p.audience:
        parts.append(f"【受众】{p.audience}")
    if pillars:
        parts.append(f"【内容支柱】{pillars}")
    if p.values:
        parts.append(f"【价值观】{p.values}")
    if p.catchphrase:
        parts.append(f"【口头禅/开场白】{p.catchphrase}")
    if p.cta_style:
        parts.append(f"【行动号召风格】{p.cta_style}")
    parts.append(f"【偏好时长】{p.video_duration}秒")
    if taboo:
        parts.append(f"【禁忌词（绝对禁止使用）】{taboo}")
    if avoid:
        parts.append(f"【回避话题（不得涉及）】{avoid}")
    if p.style_samples:
        parts.append(f"【风格样本（模仿这个语气和节奏）】\n{p.style_samples[:800]}")
    return "\n".join(parts)


def to_out(p: Persona) -> PersonaOut:
    return PersonaOut(
        id=p.id,
        name=p.name,
        domain=p.domain,
        tone=p.tone,
        values=p.values,
        tabooWords=json.loads(p.taboo_words or "[]"),
        avatarChar=p.avatar_char,
        avatarGrad=p.avatar_grad,
        voiceId=p.voice_id,
        avatarId=p.avatar_id,
        isActive=p.is_active,
        audience=p.audience or "",
        contentPillars=json.loads(p.content_pillars or "[]"),
        styleSamples=p.style_samples or "",
        catchphrase=p.catchphrase or "",
        videoDuration=p.video_duration or 60,
        ctaStyle=p.cta_style or "",
        avoidTopics=json.loads(p.avoid_topics or "[]"),
    )
