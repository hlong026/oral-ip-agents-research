"""持久化队列 Actor；业务状态仍由数据库状态机管理。"""

import asyncio

import dramatiq

from .broker import broker as _broker  # noqa: F401


@dramatiq.actor(queue_name="pipeline", max_retries=0, time_limit=1_800_000)
def run_pipeline_task(task_id: str, from_step: str | None = None) -> None:
    from app.modules.pipeline.engine import run_task

    asyncio.run(run_task(task_id, from_step))


@dramatiq.actor(queue_name="publish", max_retries=0, time_limit=900_000)
def run_publish_job(job_id: str) -> None:
    from app.modules.publish.service import _run_job

    asyncio.run(_run_job(job_id))


@dramatiq.actor(queue_name="im", max_retries=0, time_limit=120_000)
def run_im_auto_reply(message_id: str) -> None:
    from app.modules.im.service import run_scheduled_reply

    asyncio.run(run_scheduled_reply(message_id))


@dramatiq.actor(queue_name="billing", max_retries=2, time_limit=300_000)
def run_credit_expiry() -> None:
    """定时扫描过期积分批次并清零。建议每 10 分钟调度一次。"""
    from app.modules.billing.tasks import expire_credits

    asyncio.run(expire_credits())


@dramatiq.actor(queue_name="billing", max_retries=2, time_limit=300_000)
def run_plan_expiry_reminder() -> None:
    """套餐到期提醒：到期前 7/3/1 天发送站内信 + WebSocket 推送。建议每小时调度一次。"""
    from app.modules.billing.tasks import remind_plan_expiry

    asyncio.run(remind_plan_expiry())
