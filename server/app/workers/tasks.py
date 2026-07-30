"""持久化队列 Actor；业务状态仍由数据库状态机管理。"""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

import dramatiq

from app.core.runtime_limits import PIPELINE_ACTOR_TIME_LIMIT_MS, PUBLISH_ACTOR_TIME_LIMIT_MS

from .broker import broker as _broker  # noqa: F401

T = TypeVar("T")
_worker_loop: asyncio.AbstractEventLoop | None = None


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """让同一 Worker 进程内的异步连接始终归属同一个事件循环。"""
    global _worker_loop

    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop.run_until_complete(coro)


@dramatiq.actor(queue_name="pipeline", max_retries=3, time_limit=PIPELINE_ACTOR_TIME_LIMIT_MS, retry_interval=60_000)
def run_pipeline_task(task_id: str, from_step: str | None = None) -> None:
    from app.modules.pipeline.engine import run_task

    _run_async(run_task(task_id, from_step))


@dramatiq.actor(queue_name="pipeline", max_retries=3, time_limit=PIPELINE_ACTOR_TIME_LIMIT_MS, retry_interval=60_000)
def run_pipeline_render(render_id: str) -> None:
    from app.modules.pipeline.render import run_render_version

    _run_async(run_render_version(render_id))


@dramatiq.actor(queue_name="content", max_retries=2, time_limit=PIPELINE_ACTOR_TIME_LIMIT_MS)
def run_content_job(job_id: str) -> None:
    from app.modules.content.jobs import run_content_job as run

    _run_async(run(job_id))


@dramatiq.actor(queue_name="publish", max_retries=3, time_limit=PUBLISH_ACTOR_TIME_LIMIT_MS, retry_interval=60_000)
def run_publish_job(job_id: str) -> None:
    from app.modules.publish.service import _run_job

    _run_async(_run_job(job_id))


@dramatiq.actor(queue_name="webhook", max_retries=0, time_limit=120_000)
def run_webhook_retry(event_id: str) -> None:
    from app.modules.webhook.service import retry_failed_event

    _run_async(retry_failed_event(event_id))


@dramatiq.actor(queue_name="im", max_retries=0, time_limit=120_000)
def run_im_auto_reply(message_id: str) -> None:
    from app.modules.im.service import run_scheduled_reply

    _run_async(run_scheduled_reply(message_id))
