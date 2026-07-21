"""
Cookie 有效性心跳检测
- 定时（30min）检测所有 active 账号的 Cookie 是否仍然有效
- 失效时：更新状态为 expired + 推送告警到前端
- 在 app 启动时注册后台任务
"""
import asyncio
import json

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events import CHANNEL_ALERT
from app.core.events import publish as emit
from app.core.logging import get_logger
from app.providers.registry import registry

logger = get_logger("oral.publish.heartbeat")

# 心跳间隔（秒）：从配置读取，默认 30 分钟
HEARTBEAT_INTERVAL = get_settings().publish_cookie_heartbeat_min * 60


async def check_all_accounts() -> None:
    """检测所有 active 账号的 Cookie 有效性"""
    from sqlalchemy import select

    from app.modules.publish.models import PublishAccount

    async with SessionLocal() as db:
        result = await db.execute(
            select(PublishAccount).where(PublishAccount.status == "active")
        )
        accounts = result.scalars().all()

    if not accounts:
        return

    logger.info("heartbeat_start", count=len(accounts))
    expired_count = 0

    for account in accounts:
        try:
            driver = registry.publish_driver(account.platform)
            # 检查 driver 是否支持 cookie 检测（SAU Driver 支持，Mock 不支持）
            if not hasattr(driver, "check_cookie_valid"):
                continue

            session = json.loads(account.session_json or "{}")
            valid = await driver.check_cookie_valid(session, account_id=account.id)

            if not valid:
                expired_count += 1
                # 更新状态
                async with SessionLocal() as db:
                    from app.modules.publish.repository import get_account, save_account
                    acc = await get_account(db, account.id, account.user_id)
                    if acc and acc.status == "active":
                        acc.status = "expired"
                        await save_account(db, acc)

                # 推送告警
                platform_names = {"douyin": "抖音",
                                  "xiaohongshu": "小红书", "shipinhao": "视频号"}
                await emit(CHANNEL_ALERT, {
                    "level": "warning",
                    "userId": account.user_id,
                    "message": f"{platform_names.get(account.platform, account.platform)}"
                               f"账号「{account.nickname}」登录态已失效，请重新授权",
                    "accountId": account.id,
                })
                logger.warning(
                    "account_expired",
                    account_id=account.id,
                    platform=account.platform,
                    user_id=account.user_id,
                )
        except Exception as e:
            logger.debug("heartbeat_check_error", account_id=account.id, error=str(e)[:100])

    if expired_count:
        logger.warning("heartbeat_done", expired=expired_count, total=len(accounts))
    else:
        logger.info("heartbeat_done", expired=0, total=len(accounts))


async def heartbeat_loop() -> None:
    """后台心跳循环（app 生命周期内持续运行）"""
    # 首次延迟 5 分钟再检测（避免启动时资源竞争）
    await asyncio.sleep(300)
    while True:
        try:
            await check_all_accounts()
        except Exception as e:
            logger.error("heartbeat_loop_error", error=str(e)[:200])
        await asyncio.sleep(HEARTBEAT_INTERVAL)


def start_heartbeat() -> asyncio.Task:
    """启动心跳后台任务（在 app lifespan 中调用）"""
    loop = asyncio.get_running_loop()
    task = loop.create_task(heartbeat_loop())
    logger.info("heartbeat_started", interval_sec=HEARTBEAT_INTERVAL)
    return task
