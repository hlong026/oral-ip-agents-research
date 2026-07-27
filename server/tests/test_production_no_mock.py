"""生产切换去 Mock 的 CI 门禁（机制性防线回归）：

1. prod 语义下 ProviderRegistry 各链与发布驱动零 Mock，且 fail-fast 自检生效；
2. Settings.mock_fallback_allowed 非 dev/test 无条件 False（不受 .env 误配影响）；
3. pipeline `_guard_mock_result` prod 拒收 Mock 产物、dev/test 放行并打 degraded_mock 标记。
"""

from types import SimpleNamespace

import pytest

from app.providers.base import is_mock_provider


def _prod_settings(**overrides) -> SimpleNamespace:
    base = {
        "app_env": "prod",
        "provider_mock_fallback_enabled": None,
        "im_enabled": False,
        "douyin_im_app_key": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ============ 1. 注册表：prod 零 Mock + fail-fast ============


def test_prod_registry_has_zero_mock_providers(monkeypatch) -> None:
    from app.providers import registry as registry_module

    monkeypatch.setattr(registry_module, "get_settings", lambda: _prod_settings())
    prod_registry = registry_module.ProviderRegistry()

    snapshot = prod_registry.chain_snapshot()
    # 六条降级链 + publish 驱动全部覆盖
    assert set(snapshot) == {"llm", "parse", "asr", "voice", "avatar", "compose", "publish"}
    for kind, names in snapshot.items():
        assert names, f"{kind} 链不允许为空"
        assert not any(is_mock_provider(n) for n in names), f"{kind} 链混入 Mock：{names}"
    assert prod_registry.has_mock_providers() is False


def test_prod_registry_fail_fast_on_leaked_mock(monkeypatch) -> None:
    """任何链一旦混入 mock- provider，自检必须抛异常拒绝启动。"""
    from app.providers import registry as registry_module
    from app.providers.mock import MockLLM

    monkeypatch.setattr(registry_module, "get_settings", lambda: _prod_settings())
    prod_registry = registry_module.ProviderRegistry()

    prod_registry.llm_chain.append(MockLLM())
    with pytest.raises(RuntimeError, match="禁止加载 Mock Provider"):
        prod_registry._assert_no_mock_providers()


def test_prod_registry_ignores_misconfigured_mock_flag(monkeypatch) -> None:
    """即使 .env 误配 PROVIDER_MOCK_FALLBACK_ENABLED=true，prod 也不追加 Mock 链尾。"""
    from app.providers import registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "get_settings",
        lambda: _prod_settings(provider_mock_fallback_enabled=True),
    )
    prod_registry = registry_module.ProviderRegistry()
    assert prod_registry.has_mock_providers() is False


# ============ 2. Settings：mock 开关按环境推导 ============


def test_mock_fallback_allowed_derived_by_env() -> None:
    from app.core.config import Settings

    # 非 dev/test 无条件 False，显式误配 True 也不放行
    assert Settings(app_env="prod").mock_fallback_allowed is False
    assert Settings(app_env="prod", provider_mock_fallback_enabled=True).mock_fallback_allowed is False
    assert Settings(app_env="staging").mock_fallback_allowed is False
    # dev/test 未显式配置默认放行，显式关闭则关闭
    assert Settings(app_env="dev").mock_fallback_allowed is True
    assert Settings(app_env="test").mock_fallback_allowed is True
    assert Settings(app_env="dev", provider_mock_fallback_enabled=False).mock_fallback_allowed is False


# ============ 3. pipeline：prod 拒收 Mock 产物 / dev 打标放行 ============


def _fake_task() -> SimpleNamespace:
    return SimpleNamespace(id="task-guard", user_id="user-guard")


async def test_guard_rejects_mock_result_in_prod(monkeypatch) -> None:
    from app.modules.pipeline import engine

    monkeypatch.setattr(engine, "get_settings", lambda: _prod_settings())
    with pytest.raises(RuntimeError, match="演示数据"):
        await engine._guard_mock_result(_fake_task(), "voice", "mock-voice", {"audio": "x"})


async def test_guard_marks_degraded_mock_in_dev(monkeypatch) -> None:
    from app.modules.pipeline import engine

    monkeypatch.setattr(engine, "get_settings", lambda: _prod_settings(app_env="dev"))
    events: list[dict] = []

    async def fake_publish(channel, payload):
        events.append(payload)

    monkeypatch.setattr(engine, "publish", fake_publish)

    result = await engine._guard_mock_result(_fake_task(), "asr", "mock-faster-whisper", {"text": "demo"})
    assert result["degraded_mock"] is True
    assert events and events[0]["kind"] == "degraded_mock" and events[0]["step"] == "asr"


async def test_guard_passes_real_provider_result(monkeypatch) -> None:
    from app.modules.pipeline import engine

    monkeypatch.setattr(engine, "get_settings", lambda: _prod_settings())
    result = await engine._guard_mock_result(_fake_task(), "avatar", "hifly-avatar", {"video": "v"})
    assert "degraded_mock" not in result
