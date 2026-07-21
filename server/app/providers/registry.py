"""
Provider 注册表（06 文档 §10.3）
- 三级解析：用户配置 → 租户默认 → 系统默认
- 降级链自动切换并记事件（任务中心可见）
- 新增供应商 = 新建文件实现 Protocol + 在此注册一行
- 日志：降级链 WARNING/ERROR（§10.6.8-A #4）+ 调用耗时（§10.6.8-B #5）
"""

import time
from typing import Any

from app.core.config import get_settings
from app.core.events import CHANNEL_TASKS, publish
from app.core.logging import get_logger

from .aliyun_asr import AliyunASR
from .base import (
    ASRProvider,
    AvatarProvider,
    ComposeEngine,
    LLMProvider,
    ParseProvider,
    PublishDriver,
    VoiceProvider,
)
from .douyidou import DouyidouParser
from .hifly import HiFlyAvatar, HiFlyVoice
from .im.base import IMProvider
from .im.douyin_im import DouyinIMProvider
from .im.mock_im import MockIMProvider
from .mock import MockASR, MockAvatar, MockCompose, MockLLM, MockParser, MockPublishDriver, MockVoice
from .publish.douyin import DouyinPublishDriver
from .publish.tencent import TencentPublishDriver
from .publish.xiaohongshu import XiaohongshuPublishDriver
from .real import DeepSeekLLM, FFmpegCompose, ThirdPartyParser

logger = get_logger("oral.providers.registry")


class ProviderRegistry:
    """每类 Provider 持有「主实现 → 备用实现」降级链（配置由前端设置页管理，未配置时自动降级到 Mock）"""

    def __init__(self) -> None:
        self.llm_chain: list[LLMProvider] = [DeepSeekLLM(), MockLLM()]
        self.parse_chain: list[ParseProvider] = [DouyidouParser(), ThirdPartyParser(), MockParser()]
        self.asr_chain: list[ASRProvider] = [AliyunASR(), MockASR()]
        self.voice_chain: list[VoiceProvider] = [HiFlyVoice(), MockVoice()]
        self.avatar_chain: list[AvatarProvider] = [HiFlyAvatar(), MockAvatar()]
        self.compose_chain: list[ComposeEngine] = [FFmpegCompose(), MockCompose()]
        # 发布驱动：SAU 浏览器自动化（真实）→ Mock（降级兜底）
        self.publish_drivers: dict[str, PublishDriver] = {
            "douyin": DouyinPublishDriver(),
            "xiaohongshu": XiaohongshuPublishDriver(),
            "shipinhao": TencentPublishDriver(),
        }
        self._publish_mock_fallback: dict[str, PublishDriver] = {
            p: MockPublishDriver(p) for p in ("douyin", "xiaohongshu", "shipinhao")
        }
        # IM Provider：生产默认真实链路；Mock 只能由测试/演示环境显式开启。
        _use_mock_im = get_settings().douyin_im_use_mock
        self.im_drivers: dict[str, IMProvider] = {
            "douyin": MockIMProvider() if _use_mock_im else DouyinIMProvider(),
        }

    async def run_with_fallback(
        self, kind: str, chain: list, fn_name: str, *args, trace_id: str = "", task_id: str = "", **kwargs
    ):
        """沿降级链执行；StepRecoverableError 触发切换，降级事件推任务中心"""
        from .base import StepRecoverableError

        last_err: Exception | None = None
        for idx, provider in enumerate(chain):
            try:
                t0 = time.perf_counter()
                result = await getattr(provider, fn_name)(*args, **kwargs)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                # Provider API 调用耗时日志（§10.6.8-B #5）
                logger.info(
                    "provider_api_call",
                    kind=kind,
                    provider_name=provider.name,
                    fn_name=fn_name,
                    duration_ms=elapsed_ms,
                    trace_id=trace_id,
                    task_id=task_id,
                )
                if idx > 0:
                    # 降级成功：记录 WARNING
                    logger.warning(
                        "provider_fallback",
                        kind=kind,
                        from_provider=chain[idx - 1].name if idx > 0 else "",
                        to_provider=provider.name,
                        fn_name=fn_name,
                        trace_id=trace_id,
                        task_id=task_id,
                    )
                    await publish(
                        CHANNEL_TASKS,
                        {
                            "kind": "provider_fallback",
                            "provider_kind": kind,
                            "to": provider.name,
                            "taskId": task_id,
                            "traceId": trace_id,
                            "message": f"{kind} 已降级到 {provider.name}",
                        },
                    )
                return result, provider.name
            except StepRecoverableError as e:
                # 降级链中某 Provider 失败：记录 WARNING
                logger.warning(
                    "provider_attempt_failed",
                    kind=kind,
                    provider_name=provider.name,
                    fn_name=fn_name,
                    error=str(e)[:200],
                    trace_id=trace_id,
                    task_id=task_id,
                )
                last_err = e
                continue
        # 降级链全部失败：记录 ERROR
        logger.error(
            "provider_chain_exhausted",
            kind=kind,
            fn_name=fn_name,
            trace_id=trace_id,
            task_id=task_id,
            error=str(last_err)[:200] if last_err else "unknown",
        )
        raise last_err or RuntimeError(f"{kind} 无可用 Provider")

    def publish_driver(self, platform: str) -> PublishDriver:
        return self.publish_drivers[platform]

    def im_driver(self, platform: str) -> IMProvider:
        driver = self.im_drivers.get(platform)
        if driver is None:
            raise RuntimeError(f"no IM driver for platform: {platform}")
        return driver

    def get(self, kind: str):
        """按类型获取链首 Provider（供 im 等模块直接调用 LLM）"""
        chain_map: dict[str, list[Any]] = {
            "llm": self.llm_chain,
            "parse": self.parse_chain,
            "asr": self.asr_chain,
            "voice": self.voice_chain,
            "avatar": self.avatar_chain,
            "compose": self.compose_chain,
        }
        chain = chain_map.get(kind)
        if not chain:
            raise RuntimeError(f"unknown provider kind: {kind}")
        return chain[0]


registry = ProviderRegistry()
