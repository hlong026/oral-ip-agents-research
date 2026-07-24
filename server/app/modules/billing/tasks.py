"""billing 定时任务：积分过期清零 + 套餐到期提醒。

调度方式：
- run_credit_expiry: 每 10 分钟（Dramatiq periodic 或 cron）
- run_plan_expiry_reminder: 每小时
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select

from app.core.db import SessionLocal
from app.core.logging import get_logger

logger = get_logger("oral.billing.tasks")

REMINDER_DAYS = (7, 3, 1)


async def expire_credits() -> None:
    """扫描并清零过期积分批次。"""
    from app.modules.billing.service import expire_overdue_grants

    total = 0
    async with SessionLocal() as db:
        while True:
            count = await expire_overdue_grants(db, batch_size=200)
            total += count
            if count < 200:
                break
    if total > 0:
        logger.info("credit_expiry_task_complete", total_expired=total)


async def remind_plan_expiry() -> None:
    """套餐到期提醒：到期前 7/3/1 天发送站内信 + WebSocket 推送。

    幂等：通过检查当天是否已发送过同类型通知来避免重复推送。
    """
    from app.modules.auth.models import User
    from app.modules.notify.models import Notification
    from app.modules.notify.service import notify_user

    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with SessionLocal() as db:
        for days_before in REMINDER_DAYS:
            target_date = now + timedelta(days=days_before)
            window_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            window_end = window_start + timedelta(days=1)

            users = list(
                (
                    await db.execute(
                        select(User).where(
                            and_(
                                User.plan_type != "none",
                                User.plan_expires_at.is_not(None),
                                User.plan_expires_at >= window_start,
                                User.plan_expires_at < window_end,
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )

            for user in users:
                reminder_title = f"套餐即将到期（剩余 {days_before} 天）"
                already_sent = (
                    await db.execute(
                        select(Notification.id)
                        .where(
                            Notification.user_id == user.id,
                            Notification.title == reminder_title,
                            Notification.created_at >= today_start,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if already_sent:
                    continue

                expires_str = user.plan_expires_at.strftime("%Y-%m-%d") if user.plan_expires_at else ""
                body = (
                    f"您的套餐将在 {days_before} 天后到期（{expires_str}），"
                    f"到期后相关权益将暂停。请及时续费以保持服务不中断。"
                )
                await notify_user(db, user.id, "warn", reminder_title, body)
                logger.info(
                    "plan_expiry_reminder_sent",
                    user_id=user.id,
                    days_before=days_before,
                )

        await db.commit()
