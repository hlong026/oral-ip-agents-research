"""WS 网关（06 文档 §10.1：Pub/Sub → 各端广播，进度延迟 ≤2s）
- /ws/tasks?token=<access_token>
- 订阅三频道（任务进度 / 动态流 / 告警），按 userId 过滤转发
"""
import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.deps import verify_ws_token
from app.core.events import CHANNEL_ALERT, CHANNEL_FEED, CHANNEL_IM, CHANNEL_TASKS, subscribe

logger = logging.getLogger(__name__)
ws_router = APIRouter()

PING_INTERVAL = 25  # 心跳保活（秒）


@ws_router.websocket("/ws/tasks")
async def tasks_ws(ws: WebSocket) -> None:
    token = ws.query_params.get("token", "")
    user_id = verify_ws_token(token)
    if user_id is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    getters = [await subscribe(ch) for ch in (CHANNEL_TASKS, CHANNEL_FEED, CHANNEL_ALERT, CHANNEL_IM)]

    async def pump() -> None:
        while True:
            # 轮询三频道（各 1s 超时），合并后推送，整体延迟 ≤2s
            for get in getters:
                try:
                    msg = await get()
                except Exception:  # noqa: BLE001
                    msg = None
                if msg is None:
                    continue
                if msg.get("userId") not in (None, user_id):
                    continue
                await ws.send_text(json.dumps(msg, ensure_ascii=False, default=str))

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await ws.send_text(json.dumps({"kind": "ping"}))

    pump_task = asyncio.create_task(pump())
    hb_task = asyncio.create_task(heartbeat())
    try:
        while True:
            # 接收客户端消息（目前仅作保活；预留订阅控制）
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        pump_task.cancel()
        hb_task.cancel()
