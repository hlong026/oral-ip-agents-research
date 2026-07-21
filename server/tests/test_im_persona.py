"""S3-07 IP persona injection for IM LLM replies."""

import logging
import uuid

import pytest
from httpx import AsyncClient

from app.core.db import SessionLocal
from app.modules.im import service
from app.modules.im.models import IMAutoReplyRule, IMConversation
from app.modules.ipasset import repository as persona_repo


async def test_llm_reply_uses_active_persona(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    del client
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        persona = await persona_repo.create(
            db,
            user_id,
            name="林老师",
            domain="家庭教育",
            tone="温和、克制",
            values="不制造焦虑",
            taboo_words='["保证效果"]',
            is_active=True,
        )
        rule = IMAutoReplyRule(user_id=user_id, reply_mode="llm", llm_prompt="先理解问题再回答")
        conversation = IMConversation(account_id="account-1", user_id=user_id, remote_uid="remote-1")
        db.add_all([rule, conversation])
        await db.commit()

        llm = _LLM()
        monkeypatch.setattr(service.registry, "get", lambda _kind: llm)
        reply = await service._generate_reply(db, rule, "孩子不爱学习怎么办", conversation)

    assert persona.is_active is True
    assert reply == "人设回复"
    assert "林老师" in llm.prompt
    assert "家庭教育" in llm.prompt
    assert "温和、克制" in llm.prompt
    assert "先理解问题再回答" in llm.prompt


async def test_missing_persona_explicitly_degrades_without_calling_llm(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    del client
    rule = IMAutoReplyRule(user_id="user-without-persona", reply_mode="llm", reply_template="请稍后由人工回复")
    conversation = IMConversation(account_id="account-2", user_id=rule.user_id, remote_uid="remote-2")
    monkeypatch.setattr(service.registry, "get", lambda _kind: _UnexpectedLLM())

    with caplog.at_level(logging.WARNING):
        async with SessionLocal() as db:
            reply = await service._generate_reply(db, rule, "你好", conversation)

    assert reply == "请稍后由人工回复"
    assert "persona unavailable" in caplog.text


class _LLM:
    prompt = ""

    async def rewrite(self, *, text: str, intensity: str, prompt: str) -> str:
        assert text == "孩子不爱学习怎么办"
        assert intensity == "light"
        self.prompt = prompt
        return "人设回复"


class _UnexpectedLLM:
    async def rewrite(self, **_kwargs: object) -> str:
        raise AssertionError("LLM must not run without an active persona")
