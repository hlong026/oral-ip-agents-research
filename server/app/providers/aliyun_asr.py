"""
阿里云 Fun-ASR 语音转写 Provider（DashScope）
- 按时长智能分流：
  - ≤ asr_flash_threshold_sec（默认300s/5min）→ Fun-ASR-Flash 同步模式（秒级返回）
  - > 阈值 → Fun-ASR 异步模式（提交→轮询→下载结果，支持≤12h/2GB）
- 输入：公网可访问的音视频URL（Douyidou 返回的视频直链）
- 支持格式：aac, amr, flac, flv, m4a, mkv, mov, mp3, mp4, mpeg, ogg, opus, wav, webm, wma, wmv
"""

import asyncio
import logging
from typing import Any

import httpx

from app.core.dynamic_config import get_config, get_config_int

from .base import StepRecoverableError, TranscriptResult, WordTs

logger = logging.getLogger("oral.providers.aliyun_asr")


class AliyunASR:
    """阿里云 Fun-ASR 语音转写（按时长自动选择同步/异步模式，凭据从前端设置页动态读取）"""

    name = "aliyun-fun-asr"

    async def _get_config(self) -> dict[str, Any]:
        """动态读取 ASR 配置"""
        api_key = await get_config("dashscope_api_key")
        workspace_id = await get_config("dashscope_workspace_id")
        region = await get_config("dashscope_region", "cn-beijing")
        asr_model = await get_config("asr_model", "fun-asr")
        flash_model = await get_config("asr_flash_model", "fun-asr-flash-2026-06-15")
        threshold = await get_config_int("asr_flash_threshold_sec", 300)
        # 有业务空间ID走专属端点，否则走 DashScope 公共端点
        if workspace_id:
            base_url = f"https://{workspace_id}.{region}.maas.aliyuncs.com"
        else:
            base_url = "https://dashscope.aliyuncs.com"
        return {
            "api_key": api_key,
            "base_url": base_url,
            "asr_model": asr_model,
            "flash_model": flash_model,
            "threshold": threshold,
        }

    async def transcribe(self, video_key: str, duration_sec: float | None = None) -> TranscriptResult:
        """
        转写入口：根据时长分流。

        Args:
            video_key: 公网可访问的音视频URL（或本地存储key）
            duration_sec: 预估时长(秒)。None时默认走异步模式（安全兖底）
        """
        cfg = await self._get_config()
        if not cfg["api_key"]:
            raise StepRecoverableError("DashScope api_key 未配置，请在设置页填写")

        file_url = video_key

        # 按时长分流
        threshold = cfg["threshold"]
        if duration_sec is not None and duration_sec <= threshold:
            logger.info(f"ASR 走 Flash 同步模式（时长 {duration_sec:.0f}s ≤ {threshold}s）")
            return await self._transcribe_flash(file_url, cfg)
        else:
            duration_label = "未知" if duration_sec is None else f"{duration_sec:.0f}s"
            logger.info(f"ASR 走异步模式（时长 {duration_label} > {threshold}s）")
            return await self._transcribe_async(file_url, cfg)

    # ==================== 同步模式：Fun-ASR-Flash ====================

    async def _transcribe_flash(self, file_url: str, cfg: dict[str, Any]) -> TranscriptResult:
        """
        Fun-ASR-Flash 同步调用（≤5分钟短音频，秒级返回）
        POST /api/v1/services/aigc/multimodal-generation/generation
        """
        url = f"{cfg['base_url']}/api/v1/services/aigc/multimodal-generation/generation"
        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "disable",
        }
        payload = {
            "model": cfg["flash_model"],
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": file_url},
                            }
                        ],
                    }
                ]
            },
            "parameters": {
                "format": self._guess_format(file_url),
                "sample_rate": "16000",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise StepRecoverableError(f"Fun-ASR-Flash 请求失败: {e}") from e

        # 解析响应
        output = data.get("output", {})
        text = output.get("text", "")
        if not text:
            raise StepRecoverableError("Fun-ASR-Flash 返回空文本")

        # 提取词级时间戳
        words: list[WordTs] = []
        sentence = output.get("sentence", {})
        for w in sentence.get("words", []):
            words.append(
                WordTs(
                    word=w.get("text", "") + w.get("punctuation", ""),
                    start=w.get("begin_time", 0) / 1000.0,
                    end=w.get("end_time", 0) / 1000.0,
                )
            )

        duration = data.get("usage", {}).get("duration", 0)
        return TranscriptResult(text=text, words=words, duration=float(duration), language="zh")

    # ==================== 异步模式：Fun-ASR ====================

    async def _transcribe_async(self, file_url: str, cfg: dict[str, Any]) -> TranscriptResult:
        """
        Fun-ASR 异步调用（长音频，提交→轮询→下载结果）
        支持 ≤2GB / ≤12小时
        """
        task_id = await self._submit_task(file_url, cfg)
        logger.info(f"ASR 异步任务已提交: task_id={task_id}")
        result = await self._poll_task(task_id, cfg)
        return await self._download_result(result)

    async def _submit_task(self, file_url: str, cfg: dict[str, Any]) -> str:
        """提交异步转写任务，返回 task_id"""
        url = f"{cfg['base_url']}/api/v1/services/audio/asr/transcription"
        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        payload = {
            "model": cfg["asr_model"],
            "input": {
                "file_urls": [file_url],
            },
            "parameters": {
                "channel_id": [0],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise StepRecoverableError(f"ASR 提交任务失败: {e}") from e

        task_id = data.get("output", {}).get("task_id")
        if not task_id:
            raise StepRecoverableError(f"ASR 提交任务未返回 task_id: {data}")
        return task_id

    async def _poll_task(self, task_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
        """轮询任务状态直到终态（SUCCEEDED/FAILED）"""
        url = f"{cfg['base_url']}/api/v1/tasks/{task_id}"
        headers = {"Authorization": f"Bearer {cfg['api_key']}"}
        interval = 2.0
        max_attempts = 90

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            for attempt in range(max_attempts):
                await asyncio.sleep(interval)
                try:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError as e:
                    logger.warning(f"ASR 轮询请求异常(attempt={attempt + 1}): {e}")
                    continue

                output = data.get("output", {})
                status = output.get("task_status", "")

                if status == "SUCCEEDED":
                    return output
                elif status in ("FAILED", "CANCELED"):
                    # 检查子任务错误
                    results = output.get("results", [])
                    err_msg = ""
                    for r in results:
                        if r.get("subtask_status") == "FAILED":
                            err_msg = r.get("message", r.get("code", "未知错误"))
                            break
                    raise StepRecoverableError(f"ASR 任务失败: {err_msg or status}")

                # PENDING / RUNNING → 继续轮询
                if (attempt + 1) % 10 == 0:
                    logger.info(f"ASR 轮询中... attempt={attempt + 1}, status={status}")

        raise StepRecoverableError(f"ASR 轮询超时（{max_attempts * interval:.0f}s）")

    async def _download_result(self, output: dict[str, Any]) -> TranscriptResult:
        """下载 transcription_url 并解析为 TranscriptResult"""
        results = output.get("results", [])
        if not results:
            raise StepRecoverableError("ASR 结果为空")

        # 取第一个成功的子任务
        transcription_url = None
        for r in results:
            if r.get("subtask_status") == "SUCCEEDED" and r.get("transcription_url"):
                transcription_url = r["transcription_url"]
                break

        if not transcription_url:
            raise StepRecoverableError("ASR 无有效的 transcription_url")

        # 下载 JSON 结果
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.get(transcription_url)
                resp.raise_for_status()
                result_data = resp.json()
        except httpx.HTTPError as e:
            raise StepRecoverableError(f"ASR 结果下载失败: {e}") from e

        # 解析 JSON 结构
        return self._parse_transcription(result_data)

    def _parse_transcription(self, data: dict[str, Any]) -> TranscriptResult:
        """
        解析 Fun-ASR 转写结果 JSON：
        {file_url, properties:{...}, transcripts:[{channel_id, text, sentences:[...]}]}
        """
        transcripts = data.get("transcripts", [])
        if not transcripts:
            raise StepRecoverableError("ASR 转写结果无 transcripts")

        # 取第一个音轨
        tr = transcripts[0]
        full_text = tr.get("text", "")
        duration_ms = data.get("properties", {}).get("original_duration_in_milliseconds", 0)

        # 提取词级时间戳
        words: list[WordTs] = []
        for sentence in tr.get("sentences", []):
            for w in sentence.get("words", []):
                words.append(
                    WordTs(
                        word=w.get("text", "") + w.get("punctuation", ""),
                        start=w.get("begin_time", 0) / 1000.0,
                        end=w.get("end_time", 0) / 1000.0,
                    )
                )

        return TranscriptResult(
            text=full_text,
            words=words,
            duration=duration_ms / 1000.0,
            language="zh",
        )

    @staticmethod
    def _guess_format(url: str) -> str:
        """从URL推断音频格式"""
        ext_map = {
            ".mp4": "mp4",
            ".mp3": "mp3",
            ".wav": "wav",
            ".aac": "aac",
            ".flac": "flac",
            ".ogg": "ogg",
            ".opus": "opus",
            ".m4a": "m4a",
            ".mov": "mov",
            ".flv": "flv",
            ".webm": "webm",
            ".wma": "wma",
            ".wmv": "wmv",
            ".mkv": "mkv",
            ".amr": "amr",
        }
        lower = url.lower().split("?")[0]  # 去掉查询参数
        for ext, fmt in ext_map.items():
            if lower.endswith(ext):
                return fmt
        return "mp4"  # 默认视频格式
