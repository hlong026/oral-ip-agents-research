"""
快手 PublishDriver（基于 social-auto-upload ks_uploader）
- 扫码登录：get_ks_cookie → 二维码回调 → Cookie 落库
- 发布：KSVideo 上传视频 + 标题/话题/定时
- Cookie 检测：cookie_auth
"""
from typing import Any

from app.core.logging import get_logger

from .base_driver import SAUPublishDriverBase

logger = get_logger("oral.publish.kuaishou")


class KuaishouPublishDriver(SAUPublishDriverBase):
    name = "sau-kuaishou"
    platform = "kuaishou"

    # 登录后抓取昵称：访问快手创作者中心
    _nickname_url = "https://cp.kuaishou.com/profile"
    _nickname_selectors = [
        ".user-name",
        ".profile-name",
        "[class*='nickname']",
        "[class*='user-info'] .name",
        ".header-user .name",
        "span[class*='name']",
    ]

    async def _do_login(self, ticket: str, account_file: str) -> None:
        """调用 SAU get_ks_cookie 执行扫码登录"""
        from uploader.ks_uploader.main import get_ks_cookie

        session_data = self._login_sessions.get(ticket)
        if not session_data:
            return

        async def qrcode_callback(payload: dict) -> None:
            session_data["qrcode_info"] = payload

        try:
            result = await get_ks_cookie(
                account_file,
                qrcode_callback=qrcode_callback,
                headless=True,
                poll_interval=3,
                max_checks=100,
            )
            if result.get("success"):
                session_data["status"] = "success"
                nickname = await self._extract_nickname(account_file)
                session_data["nickname"] = nickname or "快手账号"
                logger.info("kuaishou_login_success", ticket=ticket, nickname=nickname)
            else:
                session_data["status"] = "failed"
                logger.warning("kuaishou_login_failed", ticket=ticket, msg=result.get("message", ""))
        except Exception as e:
            session_data["status"] = "failed"
            logger.error("kuaishou_login_error", ticket=ticket, error=str(e)[:200])

    async def _do_publish(self, cookie_file: str, video_path: str, title: str,
                          topics: list[str], cover_path: str | None, publish_date) -> str:
        """调用 SAU KSVideo 执行发布"""
        from uploader.ks_uploader.main import KSVideo

        uploader = KSVideo(
            title=title,
            file_path=video_path,
            tags=topics,
            publish_date=publish_date,
            account_file=cookie_file,
            headless=True,
        )
        await uploader.main()
        logger.info("kuaishou_publish_success", title=title[:30])
        return f"ks_{hash(title + video_path) % 10**8:08d}"

    async def _do_check_cookie(self, cookie_file: str) -> bool:
        """调用 SAU cookie_auth 检测快手 Cookie 有效性"""
        from uploader.ks_uploader.main import cookie_auth
        return await cookie_auth(cookie_file)
