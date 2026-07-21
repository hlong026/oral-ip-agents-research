"""
抖音 PublishDriver（基于 social-auto-upload douyin_uploader）
- 扫码登录：douyin_cookie_gen → 二维码回调 → Cookie 落库
- 发布：DouYinVideo 上传视频 + 标题/话题/封面/定时
- Cookie 检测：cookie_auth
"""

from app.core.logging import get_logger

from .base_driver import SAUPublishDriverBase

logger = get_logger("oral.publish.douyin")


class DouyinPublishDriver(SAUPublishDriverBase):
    name = "sau-douyin"
    platform = "douyin"

    # 登录后抓取昵称：访问创作者中心首页
    _nickname_url = "https://creator.douyin.com/creator-micro/home"
    # 抖音创作者平台用户信息接口（Cookie 鉴权，返回 {user: {nickname, ...}}）
    _nickname_api = ("https://creator.douyin.com/web/api/media/user/info/", "GET", None)
    _nickname_paths = [
        ["user", "nickname"],
        ["data", "user", "nickname"],
        ["nickname"],
    ]
    _sniff_keywords = ["user/info", "user_info", "creator-micro/home"]
    _nickname_selectors = [
        "span.creator-name",
        ".creator-info .name",
        "[class*='nickname']",
        "[class*='user-name']",
        ".semi-avatar + span",
        "header [class*='name']",
    ]

    async def _do_login(self, ticket: str, account_file: str) -> None:
        """调用 SAU douyin_cookie_gen 执行扫码登录"""
        from uploader.douyin_uploader.main import douyin_cookie_gen

        from app.core.config import get_settings

        headless = get_settings().publish_browser_headless

        session_data = self._login_sessions.get(ticket)
        if not session_data:
            return

        async def qrcode_callback(payload: dict) -> None:
            session_data["qrcode_info"] = payload

        try:
            result = await douyin_cookie_gen(
                account_file,
                qrcode_callback=qrcode_callback,
                headless=headless,
                poll_interval=3,
                max_checks=100,
            )
            if result.get("success"):
                # 先抓取真实昵称，再标记成功（避免轮询在昵称就绪前命中 success 拿到兜底名）
                nickname = await self._extract_nickname(account_file)
                session_data["nickname"] = nickname or f"抖音账号-{ticket[-4:]}"
                session_data["status"] = "success"
                logger.info("douyin_login_success", ticket=ticket, nickname=nickname)
            else:
                session_data["status"] = "failed"
                session_data["error"] = result.get("message", "抖音登录失败")
                logger.warning("douyin_login_failed", ticket=ticket, msg=result.get("message", ""))
        except Exception as e:
            session_data["status"] = "failed"
            session_data["error"] = str(e)[:200]
            logger.error("douyin_login_error", ticket=ticket, error=str(e)[:200])

    async def _do_publish(
        self, cookie_file: str, video_path: str, title: str, topics: list[str], cover_path: str | None, publish_date
    ) -> str:
        """调用 SAU DouYinVideo 执行发布"""
        from uploader.douyin_uploader.main import DouYinVideo

        uploader = DouYinVideo(
            title=title,
            file_path=video_path,
            tags=topics,
            publish_date=publish_date,
            account_file=cookie_file,
            thumbnail_portrait_path=cover_path,
            headless=True,
        )
        await uploader.douyin_upload_video()
        logger.info("douyin_publish_success", title=title[:30])
        # 抖音不直接返回 post_id，用标题哈希作为标识
        return f"dy_{hash(title + video_path) % 10**8:08d}"

    async def _do_check_cookie(self, cookie_file: str) -> bool:
        """调用 SAU cookie_auth 检测抖音 Cookie 有效性"""
        from uploader.douyin_uploader.main import cookie_auth

        return await cookie_auth(cookie_file)
