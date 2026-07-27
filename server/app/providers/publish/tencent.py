"""
视频号 PublishDriver（基于 social-auto-upload tencent_uploader）
- 扫码登录：tencent_cookie_gen → 二维码回调 → Cookie 落库
- 发布：TencentVideo 上传视频 + 标题/话题/定时
- Cookie 检测：cookie_auth
"""

from app.core.logging import get_logger

from .base_driver import SAUPublishDriverBase

logger = get_logger("oral.publish.tencent")


class TencentPublishDriver(SAUPublishDriverBase):
    name = "sau-tencent"
    platform = "shipinhao"

    # 登录后抓取昵称：访问视频号助手首页
    _nickname_url = "https://channels.weixin.qq.com/home"
    # 视频号助手账号信息接口（Cookie 鉴权，返回 {data: {finderUser: {nickname, ...}}}）
    _nickname_api = (
        "https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/auth/auth_data",
        "POST",
        {},
    )
    _nickname_paths = [
        ["data", "finderUser", "nickname"],
        ["finderUser", "nickname"],
    ]
    _sniff_keywords = ["auth_data", "finder"]
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

        from app.core.config import get_settings

        headless = get_settings().publish_browser_headless

        session_data = self._login_sessions.get(ticket)
        if not session_data:
            return

        async def qrcode_callback(payload: dict) -> None:
            session_data["qrcode_info"] = payload

        try:
            result = await tencent_cookie_gen(
                account_file,
                qrcode_callback=qrcode_callback,
                headless=headless,
                poll_interval=3,
                max_checks=100,
            )
            if result.get("success"):
                # 先抓取真实昵称，再标记成功（避免轮询在昵称就绪前命中 success 拿到兜底名）
                nickname = await self._extract_nickname(account_file)
                session_data["nickname"] = nickname or f"视频号账号-{ticket[-4:]}"
                session_data["status"] = "success"
                logger.info("tencent_login_success", ticket=ticket, nickname=nickname)
            else:
                session_data["status"] = "failed"
                session_data["error"] = result.get("message", "视频号登录失败")
                logger.warning("tencent_login_failed", ticket=ticket, msg=result.get("message", ""))
        except Exception as e:
            session_data["status"] = "failed"
            session_data["error"] = str(e)[:200]
            logger.error("tencent_login_error", ticket=ticket, error=str(e)[:200])

    async def _do_publish(
        self, cookie_file: str, video_path: str, title: str, topics: list[str], cover_path: str | None, publish_date
    ) -> str:
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
        # SAU 拿不到视频号作品 ID，用标题哈希生成内部追踪号（postIdSource=internal）
        return f"wx_{hash(title + video_path) % 10**8:08d}"

    async def _do_check_cookie(self, cookie_file: str) -> bool:
        """调用 SAU cookie_auth 检测视频号 Cookie 有效性"""
        from uploader.tencent_uploader.main import cookie_auth

        return await cookie_auth(cookie_file)
