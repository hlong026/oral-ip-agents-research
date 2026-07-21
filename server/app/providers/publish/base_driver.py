"""
SAU PublishDriver 公共基类
- 封装 Cookie 文件管理、浏览器槽位、错误转换等公共逻辑
- 各平台 Driver 继承本类，实现 qrcode_login / check_login / publish
"""

import asyncio
import uuid
from typing import Any

from app.core.logging import get_logger
from app.core.storage import local_path
from app.providers.base import StepRecoverableError

from .browser_pool import BrowserSlot
from .cookie_manager import file_to_session, session_to_file
from .sau_conf import LOCAL_CHROME_PATH, setup_sau

logger = get_logger("oral.publish.driver")

# 确保 SAU 环境已初始化（仅首次 import 时执行）
setup_sau()


class SAUPublishDriverBase:
    """四平台 PublishDriver 公共基类"""

    name: str = "sau-base"
    platform: str = ""

    # 平台中文名（用于昵称提取失败时的兜底文案）
    _PLATFORM_CN: dict[str, str] = {
        "douyin": "抖音",
        "xiaohongshu": "小红书",
        "shipinhao": "视频号",
    }

    @property
    def _platform_cn(self) -> str:
        return self._PLATFORM_CN.get(self.platform, self.platform)

    def __init__(self) -> None:
        # 登录会话缓存：ticket → {account_file, qrcode_info, status}
        self._login_sessions: dict[str, dict[str, Any]] = {}

    # ============ PublishDriver Protocol 实现 ============

    async def qrcode_login(self) -> dict[str, str]:
        """发起扫码登录，返回 {ticket, qrcodeUrl}"""
        ticket = uuid.uuid4().hex[:16]
        account_file = self._make_login_cookie_path(ticket)

        session_data: dict[str, Any] = {
            "account_file": account_file,
            "status": "waiting",
            "qrcode_info": None,
        }
        self._login_sessions[ticket] = session_data

        # 异步启动登录流程（不阻塞 API 响应）
        asyncio.get_running_loop().create_task(self._do_login(ticket, account_file))

        # 等待二维码生成（最多 30s）
        for _ in range(60):
            await asyncio.sleep(0.5)
            info = session_data.get("qrcode_info")
            if info and info.get("image_data_url"):
                return {"ticket": ticket, "qrcodeUrl": info["image_data_url"]}
            if session_data["status"] in ("success", "failed"):
                break

        # 超时仍返回 ticket，前端继续轮询
        return {"ticket": ticket, "qrcodeUrl": ""}

    async def check_login(self, ticket: str) -> dict[str, Any] | None:
        """轮询登录状态
        - 成功：返回 session dict
        - 失败：返回 {"_failed": True, ...}
        - 等待中：返回 {"_waiting": True, "qrcode_url": ...}（二维码过期刷新后前端可拿到最新图）
        - ticket 不存在：返回 None
        """
        session_data = self._login_sessions.get(ticket)
        if not session_data:
            return None
        if session_data["status"] == "success":
            # 读取 Cookie 文件内容作为 session
            cookie_path = session_data["account_file"]
            try:
                import json
                from pathlib import Path

                def _read_session() -> dict[str, Any]:
                    return json.loads(Path(cookie_path).read_text(encoding="utf-8"))

                session = await asyncio.to_thread(_read_session)
                session["nickname"] = session_data.get("nickname") or f"{self._platform_cn}账号"
            except Exception:
                session = {"nickname": f"{self._platform_cn}账号"}
            # 清理
            del self._login_sessions[ticket]
            return session
        if session_data["status"] == "failed":
            del self._login_sessions[ticket]
            return {"_failed": True, "message": session_data.get("error", "登录失败，请重试")}
        info = session_data.get("qrcode_info") or {}
        return {"_waiting": True, "qrcode_url": info.get("image_data_url", "")}

    async def publish(
        self,
        account_session: dict[str, Any],
        video_key: str,
        title: str,
        topics: list[str],
        cover_key: str | None,
        scheduled_at: str | None = None,
        account_id: str = "",
    ) -> str:
        """执行发布，返回 post_id（平台作品ID）"""
        # 1. Cookie → 临时文件
        import json

        session_json = json.dumps(account_session, ensure_ascii=False)
        cookie_file = session_to_file(session_json, account_id or "tmp", self.platform)

        # 2. 视频/封面 → 本地绝对路径
        video_path = str(local_path(video_key))
        cover_path = str(local_path(cover_key)) if cover_key else None

        # 3. 定时发布时间解析
        publish_date = self._parse_schedule(scheduled_at)

        # 4. 在浏览器槽位内执行发布
        try:
            async with BrowserSlot():
                post_id = await self._do_publish(
                    cookie_file=cookie_file,
                    video_path=video_path,
                    title=title,
                    topics=topics,
                    cover_path=cover_path,
                    publish_date=publish_date,
                )
            # 5. 发布后回写 Cookie（SAU 发布过程中可能刷新）
            updated_session = file_to_session(account_id or "tmp", self.platform)
            if updated_session and updated_session != "{}":
                account_session.clear()
                account_session.update(json.loads(updated_session))
            return post_id
        except StepRecoverableError:
            raise
        except Exception as e:
            raise StepRecoverableError(f"{self.platform} 发布失败: {e}") from e

    async def check_cookie_valid(self, account_session: dict[str, Any], account_id: str = "") -> bool:
        """检测 Cookie 是否仍然有效（心跳用）"""
        import json

        session_json = json.dumps(account_session, ensure_ascii=False)
        cookie_file = session_to_file(session_json, account_id or "hb", self.platform)
        try:
            async with BrowserSlot():
                return await self._do_check_cookie(cookie_file)
        except Exception:
            return False

    # ============ 子类必须实现的抽象方法 ============

    async def _do_login(self, ticket: str, account_file: str) -> None:
        """执行平台登录流程（子类实现）"""
        raise NotImplementedError

    async def _do_publish(
        self, cookie_file: str, video_path: str, title: str, topics: list[str], cover_path: str | None, publish_date
    ) -> str:
        """执行平台发布（子类实现），返回 post_id"""
        raise NotImplementedError

    async def _do_check_cookie(self, cookie_file: str) -> bool:
        """检测 Cookie 有效性（子类实现）"""
        raise NotImplementedError

    # ============ 昵称抓取（三层降级） ============
    # ① 同源调用平台用户信息 JSON 接口（平台创作者后台自用接口，最稳定）
    # ② 嗅探页面加载期间的用户信息响应体
    # ③ CSS 选择器兜底（类名带哈希易失效，仅作最后手段）

    # 子类覆盖：登录后访问的页面 URL 和昵称选择器列表
    _nickname_url: str = ""
    _nickname_selectors: list[str] = []
    # 子类覆盖：平台用户信息 API —— (url, method, body|None)
    _nickname_api: tuple[str, str, dict | None] | None = None
    # 子类覆盖：昵称在 JSON 中的候选取值路径（按顺序尝试）
    _nickname_paths: list[list[str]] = []
    # 子类覆盖：嗅探时用于匹配响应 URL 的关键词
    _sniff_keywords: list[str] = []

    async def _extract_nickname(self, account_file: str) -> str:
        """登录成功后，用已保存的 Cookie 打开平台页面抓取真实昵称"""
        if not self._nickname_url:
            return ""
        try:
            from patchright.async_api import async_playwright

            from app.core.config import get_settings

            headless = get_settings().publish_browser_headless

            async with async_playwright() as pw:
                launch_kwargs: dict[str, Any] = {
                    "headless": headless,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if LOCAL_CHROME_PATH:
                    launch_kwargs["executable_path"] = LOCAL_CHROME_PATH
                else:
                    launch_kwargs["channel"] = "msedge"
                browser = await pw.chromium.launch(**launch_kwargs)
                context = await browser.new_context(storage_state=account_file)
                page = await context.new_page()

                # ② 嗅探准备：收集可能含用户信息的 JSON 响应
                sniffed: list[Any] = []
                if self._sniff_keywords:

                    async def _on_response(resp: Any) -> None:
                        try:
                            ctype = resp.headers.get("content-type") or ""
                            if "json" not in ctype:
                                return
                            if any(k in resp.url for k in self._sniff_keywords):
                                sniffed.append(await resp.json())
                        except Exception:
                            pass

                    page.on("response", _on_response)

                await page.goto(self._nickname_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2500)

                nickname = ""
                # ① 同源 fetch 平台用户信息 API（Cookie 自动携带，无 CORS 问题）
                if self._nickname_api:
                    nickname = await self._fetch_nickname_api(page)
                # ② 从嗅探到的响应体中提取
                if not nickname and sniffed:
                    for payload in sniffed:
                        nickname = self._dig_paths(payload)
                        if nickname:
                            break
                # ③ CSS 选择器兜底
                if not nickname and self._nickname_selectors:
                    nickname = await self._extract_nickname_css(page)

                await context.close()
                await browser.close()
                if nickname:
                    logger.info("nickname_extracted", platform=self.platform, nickname=nickname)
                return nickname
        except Exception as e:
            logger.warning("extract_nickname_failed", platform=self.platform, error=str(e)[:120])
            return ""

    async def _fetch_nickname_api(self, page: Any) -> str:
        """在已登录页面上下文内同源调用平台用户信息 API"""
        assert self._nickname_api is not None
        url, method, body = self._nickname_api
        try:
            payload = await page.evaluate(
                """async ([url, method, body]) => {
                    try {
                        const opts = { method, credentials: 'include' };
                        if (body !== null) {
                            opts.headers = { 'Content-Type': 'application/json' };
                            opts.body = JSON.stringify(body);
                        }
                        const resp = await fetch(url, opts);
                        if (!resp.ok) return null;
                        return await resp.json();
                    } catch (e) { return null; }
                }""",
                [url, method, body],
            )
            if payload:
                return self._dig_paths(payload)
        except Exception as e:
            logger.debug("nickname_api_failed", platform=self.platform, error=str(e)[:100])
        return ""

    def _dig_paths(self, payload: Any) -> str:
        """按候选路径列表从 JSON 中提取昵称字符串"""
        for path in self._nickname_paths:
            value = self._dig(payload, path)
            if value:
                return value
        return ""

    @staticmethod
    def _dig(data: Any, path: list[str]) -> str:
        """沿路径取字段；任一层缺失或结果不合法则返回空串"""
        cur: Any = data
        for key in path:
            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return ""
        if isinstance(cur, str):
            cur = cur.strip()
            if 0 < len(cur) <= 30:
                return cur
        return ""

    async def _extract_nickname_css(self, page: Any) -> str:
        """CSS 选择器兜底抓取页面可见昵称文本"""
        for selector in self._nickname_selectors:
            try:
                el = page.locator(selector).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and len(text) <= 30:
                        return text
            except Exception:
                continue
        return ""

    # ============ 工具方法 ============

    def _make_login_cookie_path(self, ticket: str) -> str:
        from .cookie_manager import get_cookie_dir

        return str(get_cookie_dir() / f"{self.platform}_login_{ticket}.json")

    @staticmethod
    def _parse_schedule(scheduled_at: str | None):
        """解析定时发布时间，返回 datetime 或 0（立即发布）"""
        if not scheduled_at:
            return 0
        from datetime import datetime

        try:
            dt = datetime.fromisoformat(scheduled_at)
            return dt
        except (ValueError, TypeError):
            return 0
