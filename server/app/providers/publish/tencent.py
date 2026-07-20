"""
视频号 PublishDriver（基于 social-auto-upload tencent_uploader）
- 扫码登录：tencent_cookie_gen → 二维码回调 → Cookie 落库
- 发布：TencentVideo 上传视频 + 标题/话题/定时
- Cookie 检测：cookie_auth
"""
from typing import Any

from app.core.logging import get_logger

from .base_driver import SAUPublishDriverBase

logger = get_logger("oral.publish.tencent")


class TencentPublishDriver(SAUPublishDriverBase):
    name = "sau-tencent"
    platform = "shipinhao"

    # 登录后抓取昵称：访问视频号助手首页
    _nickname_url = "https://channels.weixin.qq.com/home"
    _nickname_selectors = [
        ".nickname",
        ".account-name",
        "[class*='nickname']",
        "[class*='user-name']",
        ".finder-nickname",
        "span[class*='name']",
    ]

    async def _do_login(self, ticket: str, account_file: str) -> None:
        """调用 SAU tencent_cookie_gen 执行扫码登录"""
        from uploader.tencent_uploader.main import tencent_cookie_gen

        session_data = self._login_sessions.get(ticket)
        if not session_data:
            return

        async def qrcode_callback(payload: dict) -> None:
            session_data["qrcode_info"] = payload

        try:
            result = await tencent_cookie_gen(
                account_file,
                qrcode_callback=qrcode_callback,
                headless=True,
                poll_interval=3,
                max_checks=100,
            )
            if result.get("success"):
                session_data["status"] = "success"
                nickname = await self._extract_nickname(account_file)
                session_data["nickname"] = nickname or "视频号账号"
                logger.info("tencent_login_success", ticket=ticket, nickname=nickname)
            else:
                session_data["status"] = "failed"
                logger.warning("tencent_login_failed", ticket=ticket, msg=result.get("message", ""))
        except Exception as e:
            session_data["status"] = "failed"
            logger.error("tencent_login_error", ticket=ticket, error=str(e)[:200])

    async def _do_publish(self, cookie_file: str, video_path: str, title: str,
                          topics: list[str], cover_path: str | None, publish_date) -> str:
        """调用 SAU TencentVideo 执行发布"""
        from uploader.tencent_uploader.main import TencentVideo

        uploader = TencentVideo(
            title=title,
            file_path=video_path,
            tags=topics,
            publish_date=publish_date,
            account_file=cookie_file,
            headless=True,
        )
        await uploader.main()
        logger.info("tencent_publish_success", title=title[:30])
        return f"wx_{hash(title + video_path) % 10**8:08d}"

    async def _do_check_cookie(self, cookie_file: str) -> bool:
        """调用 SAU cookie_auth 检测视频号 Cookie 有效性"""
        from uploader.tencent_uploader.main import cookie_auth
        return await cookie_auth(cookie_file)
