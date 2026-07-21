"""Dramatiq Broker 配置；生产使用 Redis，测试使用内存 Stub。"""

import dramatiq
from dramatiq.broker import Broker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker

from app.core.config import get_settings

settings = get_settings()
broker: Broker

if settings.app_env == "test":
    broker = StubBroker()
else:
    broker = RedisBroker(url=settings.redis_url, namespace=settings.task_queue_name)

dramatiq.set_broker(broker)
