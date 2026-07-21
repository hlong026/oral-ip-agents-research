"""
小红书 PublishDriver（基于 social-auto-upload xiaohongshu_uploader）
- 扫码登录：xiaohongshu_cookie_gen → 二维码回调 → Cookie 落库
- 发布：XiaoHongShuVideo 上传视频 + 标题/话题/定时
- Cookie 检测：cookie_auth
"""
from app.core.logging import get_logger

from .base_driver import SAUPublishDriverBase

logger = get_logger("oral.publish.xiaohongshu")


class XiaohongshuPublishDriver(SAUPublishDriverBase):
    name = "sau-xiaohongshu"
    platform = "xiaohongshu"

    # 登录后抓取昵称：访问小红书创作者中心
    _nickname_url = "https://creator.xiaohongshu.com/creator/home"
    # 小红书创作者中心用户信息接口（Cookie 鉴权）
    _nickname_api = ("https://creator.xiaohongshu.com/api/galaxy/user/info", "GET", None)
    _nickname_paths = [
        ["data", "userName"],
        ["data", "userDetail", "name"],
        ["data", "nickname"],
        ["userName"],
    ]
    _sniff_keywords = ["galaxy/user", "user/info", "user/me"]
    _nickname_selectors = [
        ".user-name",
        ".creator-name",
        "[class*='nickname']",
        "[class*='user-info'] .name",
        ".header .name",
        "span[class*='name']",
    ]

    async def _do_login(self, ticket: str, account_file: str) -> None:
        """调用 SAU xiaohongshu_cookie_gen 执行扫码登录"""
        from uploader.xiaohongshu_uploader.main import xiaohongshu_cookie_gen

        from app.core.config import get_settings
        headless = get_settings().publish_browser_headless

        session_data = self._login_sessions.get(ticket)
        if not session_data:
            return

        async def qrcode_callback(payload: dict) -> None:
            session_data["qrcode_info"] = payload

        try:
            result = await xiaohongshu_cookie_gen(
                account_file,
                qrcode_callback=qrcode_callback,
                headless=headless,
                poll_interval=3,
                max_checks=100,
            )
            if result.get("success"):
                # 先抓取真实昵称，再标记成功（避免轮询在昵称就绪前命中 success 拿到兜底名）
                nickname = await self._extract_nickname(account_file)
                session_data["nickname"] = nickname or f"小红书账号-{ticket[-4:]}"
                session_data["status"] = "success"
                logger.info("xiaohongshu_login_success", ticket=ticket, nickname=nickname)
            else:
                session_data["status"] = "failed"
                session_data["error"] = result.get("message", "小红书登录失败")
                logger.warning("xiaohongshu_login_failed", ticket=ticket, msg=result.get("message", ""))
        except Exception as e:
            session_data["status"] = "failed"
            session_data["error"] = str(e)[:200]
            logger.error("xiaohongshu_login_error", ticket=ticket, error=str(e)[:200])

    async def _do_publish(self, cookie_file: str, video_path: str, title: str,
                          topics: list[str], cover_path: str | None, publish_date) -> str:
        """调用 SAU XiaoHongShuVideo 执行发布"""
        from uploader.xiaohongshu_uploader.main import XiaoHongShuVideo

        uploader = XiaoHongShuVideo(
            title=title,
            file_path=video_path,
            tags=topics,
            publish_date=publish_date,
            account_file=cookie_file,
            headless=True,
        )
        await uploader.main()
        logger.info("xiaohongshu_publish_success", title=title[:30])
        return f"xhs_{hash(title + video_path) % 10**8:08d}"

    async def _do_check_cookie(self, cookie_file: str) -> bool:
        """调用 SAU cookie_auth 检测小红书 Cookie 有效性"""
        from uploader.xiaohongshu_uploader.main import cookie_auth
        return await cookie_auth(cookie_file)
