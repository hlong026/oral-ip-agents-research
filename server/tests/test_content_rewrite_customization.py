"""IP 改写必须把当前人设和用户自定义要求交给模型。"""

from types import SimpleNamespace


async def test_structure_rewrite_passes_ip_and_custom_requirement_to_generation(
    monkeypatch,
) -> None:
    from app.modules.content import service
    from app.modules.ipasset import repository as ip_repository
    from app.modules.ipasset import service as ip_service
    from app.providers.base import SimilarityResult

    captured: dict[str, object] = {}

    class CapturingLLM:
        name = "capturing-llm"

        async def analyze_structure(self, _text: str, mode: str = "full") -> dict:
            assert mode == "full"
            return {
                "hook_type": "提问",
                "hook_text": "为什么",
                "pain_points": ["痛点"],
                "value_points": ["价值点"],
                "cta_type": "私信",
                "cta_text": "欢迎私信",
                "emotion_curve": "好奇到行动",
                "rhythm": "层层递进",
            }

        async def generate_outline(
            self,
            _structure: dict,
            persona_ctx: str,
            _intensity: str,
            _duration: int,
        ) -> str:
            captured["persona_ctx"] = persona_ctx
            return "IP 化大纲"

        async def generate_script(
            self,
            _outline: str,
            _persona_ctx: str,
            constraints: dict,
        ) -> str:
            captured["constraints"] = constraints
            return "这是根据人设生成的全新文案"

    persona = SimpleNamespace(
        video_duration=60,
        taboo_words="[]",
        cta_style="邀请私信",
        avoid_topics="[]",
    )
    llm = CapturingLLM()

    async def fake_active_persona_id(_db, _user_id: str) -> str:
        return "persona-current"

    async def fake_get_persona(_db, persona_id: str, user_id: str):
        assert persona_id == "persona-current"
        assert user_id == "user-test"
        return persona

    async def fake_similarity(*_args, **_kwargs):
        return SimilarityResult(score=0.0), "capturing-llm"

    monkeypatch.setattr(ip_service, "get_active_persona_id", fake_active_persona_id)
    monkeypatch.setattr(ip_service, "persona_prompt_context", lambda _persona: "IP：林老师")
    monkeypatch.setattr(ip_repository, "get", fake_get_persona)
    monkeypatch.setattr(service.registry, "get", lambda _kind: llm)
    monkeypatch.setattr(service.registry, "run_with_fallback", fake_similarity)

    await service.rewrite(
        None,  # type: ignore[arg-type]
        "user-test",
        "待改写原文",
        "structure",
        "保留案例，结尾邀请私信",
        None,
    )

    assert captured["persona_ctx"] == "IP：林老师"
    assert captured["constraints"] == {
        "duration": 60,
        "cta_style": "邀请私信",
        "taboo_words": "无",
        "extra_prompt": "保留案例，结尾邀请私信",
    }


async def test_light_rewrite_combines_ip_and_custom_requirement(monkeypatch) -> None:
    from app.modules.content import service
    from app.modules.ipasset import repository as ip_repository
    from app.modules.ipasset import service as ip_service

    captured: dict[str, str] = {}

    class CapturingLLM:
        name = "capturing-llm"

        async def polish_light(self, text: str, persona_ctx: str) -> str:
            captured["text"] = text
            captured["persona_ctx"] = persona_ctx
            return "轻度润色结果"

    persona = SimpleNamespace(
        video_duration=60,
        taboo_words="[]",
        cta_style="关注收藏",
        avoid_topics="[]",
    )

    async def fake_active_persona_id(_db, _user_id: str) -> str:
        return "persona-current"

    async def fake_get_persona(_db, _persona_id: str, _user_id: str):
        return persona

    monkeypatch.setattr(ip_service, "get_active_persona_id", fake_active_persona_id)
    monkeypatch.setattr(ip_service, "persona_prompt_context", lambda _persona: "IP：林老师")
    monkeypatch.setattr(ip_repository, "get", fake_get_persona)
    monkeypatch.setattr(service.registry, "get", lambda _kind: CapturingLLM())

    await service.rewrite(
        None,  # type: ignore[arg-type]
        "user-test",
        "待润色原文",
        "light",
        "保留所有数字",
        None,
    )

    assert captured["text"] == "待润色原文"
    assert captured["persona_ctx"] == ("IP：林老师\n\n【用户自定义改写要求】\n保留所有数字")


async def test_deepseek_generation_prompt_contains_custom_requirement(
    monkeypatch,
) -> None:
    from app.providers.real import DeepSeekLLM

    captured: dict[str, str] = {}
    llm = DeepSeekLLM()

    async def fake_chat(system: str, user: str, temperature: float = 0.8) -> str:
        del temperature
        captured["system"] = system
        captured["user"] = user
        return "生成结果"

    monkeypatch.setattr(llm, "_chat", fake_chat)

    await llm.generate_script(
        "IP 化大纲",
        "IP：林老师",
        {
            "duration": 60,
            "cta_style": "邀请私信",
            "taboo_words": "绝对、保证",
            "extra_prompt": "保留案例，语气更克制",
        },
    )

    assert "IP：林老师" in captured["user"]
    assert "保留案例，语气更克制" in captured["user"]
