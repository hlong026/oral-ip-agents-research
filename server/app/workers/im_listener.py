"""IM 监听 Worker（asyncio 常驻任务，管理多账号 WebSocket 连接）"""
import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# 活跃连接池：account_id → task
_active_listeners: dict[str, asyncio.Task] = {}
_connections: dict[str, Any] = {}

# #8 Cookie 心跳间隔（秒）
HEARTBEAT_INTERVAL = 30 * 60  # 30min


def start_listening(account_id: str, user_id: str) -> None:
    """启动指定账号的消息监听（非阻塞）"""
    if account_id in _active_listeners:
        logger.info(f"[IMWorker] listener already running for {account_id[:8]}")
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[IMWorker] no running event loop, cannot start listener")
        return
    task = loop.create_task(_listen_loop(account_id, user_id))
    _active_listeners[account_id] = task
    logger.info(f"[IMWorker] listener task created for {account_id[:8]}")


def stop_listening(account_id: str) -> None:
    """停止指定账号的消息监听"""
    task = _active_listeners.pop(account_id, None)
    conn = _connections.pop(account_id, None)
    if task and not task.done():
        task.cancel()
    if conn:
        t = asyncio.ensure_future(conn.close())
        t.add_done_callback(lambda _t: _t.exception() and logger.debug(f"conn.close error: {_t.exception()}"))
    logger.info(f"[IMWorker] listener stopped for {account_id[:8]}")


async def shutdown_all() -> None:
    """#7 应用关闭时清理所有监听任务"""
    for account_id in list(_active_listeners):
        stop_listening(account_id)
    if _active_listeners:
        await asyncio.gather(*_active_listeners.values(), return_exceptions=True)
    _active_listeners.clear()
    _connections.clear()
    logger.info("[IMWorker] all listeners shut down")


async def restore_listeners() -> None:
    """#7 服务重启后恢复所有 status=listening 的监听"""
    from app.core.db import SessionLocal
    from app.modules.im import repository as im_repo
    from sqlalchemy import select
    from app.modules.im.models import IMListenerState

    async with SessionLocal() as db:
        res = await db.execute(
            select(IMListenerState).where(IMListenerState.status == "listening"))
        states = list(res.scalars().all())

    for s in states:
        start_listening(s.account_id, s.user_id)
        logger.info(f"[IMWorker] restored listener for {s.account_id[:8]}")
    if states:
        logger.info(f"[IMWorker] restored {len(states)} listener(s)")


async def _check_cookie_validity(session: dict) -> bool:
    """#8 轻量级 Cookie 有效性检测"""
    import httpx
    cookie_str = session.get("cookie_str", "")
    if not cookie_str:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://www.douyin.com/aweme/v1/web/user/profile/self/",
                headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"})
            data = resp.json()
            return data.get("status_code", -1) == 0
    except Exception:  # noqa: BLE001
        return False


async def _listen_loop(account_id: str, user_id: str) -> None:
    """单账号监听主循环：连接 → 监听 → 断线重连 + Cookie 心跳"""
    from app.core.db import SessionLocal
    from app.modules.publish import repository as pub_repo
    from app.providers.registry import registry

    # 加载账号 session
    async with SessionLocal() as db:
        account = await pub_repo.get_account(db, account_id)
        if not account:
            logger.error(f"[IMWorker] account {account_id[:8]} not found")
            return
        session = json.loads(account.session_json or "{}")
        platform = account.platform

    # 获取 IM Provider
    try:
        im_provider = registry.im_driver(platform)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[IMWorker] no IM provider for {platform}: {e}")
        return

    max_retries = 5
    retry_count = 0
    last_heartbeat_time = asyncio.get_event_loop().time()

    while account_id in _active_listeners:
        try:
            # #8 Cookie 心跳检测
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                valid = await _check_cookie_validity(session)
                last_heartbeat_time = now
                async with SessionLocal() as db:
                    from app.modules.im import repository as im_repo
                    if valid:
                        await im_repo.upsert_listener_state(
                            db, account_id=account_id, user_id=user_id,
                            status="listening", last_heartbeat=datetime.now(UTC))
                    else:
                        # Cookie 过期：停止监听 + 告警
                        await im_repo.upsert_listener_state(
                            db, account_id=account_id, user_id=user_id,
                            status="error", error_msg="cookie_expired")
                        from app.core.events import publish as emit
                        from app.modules.im.events import CHANNEL_IM, EV_LISTENER_STATUS
                        await emit(CHANNEL_IM, {
                            "kind": EV_LISTENER_STATUS, "userId": user_id,
                            "accountId": account_id, "status": "error",
                            "errorMsg": "登录态失效，请重新绑定账号"})
                        logger.warning(f"[IMWorker] cookie expired for {account_id[:8]}")
                        break

            conn = await im_provider.connect(session)
            _connections[account_id] = conn
            retry_count = 0
            logger.info(f"[IMWorker] connected for {account_id[:8]}")

            async def on_message(msg: dict[str, Any]) -> None:
                from app.modules.im.service import handle_incoming_message
                await handle_incoming_message(
                    account_id=account_id,
                    user_id=user_id,
                    remote_uid=msg.get("remote_uid", ""),
                    remote_nickname=msg.get("remote_nickname", ""),
                    remote_avatar=msg.get("remote_avatar", ""),
                    msg_type=msg.get("msg_type", 7),
                    content=msg.get("content", ""),
                    dy_conversation_id=msg.get("dy_conversation_id", ""),
                    dy_conversation_short_id=msg.get("dy_conversation_short_id", ""),
                    dy_ticket=msg.get("dy_ticket", ""))

            await conn.listen(on_message)

        except asyncio.CancelledError:
            logger.info(f"[IMWorker] cancelled for {account_id[:8]}")
            break
        except Exception as e:  # noqa: BLE001
            retry_count += 1
            if retry_count > max_retries:
                logger.error(f"[IMWorker] max retries exceeded for {account_id[:8]}: {e}")
                async with SessionLocal() as db:
                    from app.modules.im import repository as im_repo
                    await im_repo.upsert_listener_state(
                        db, account_id=account_id, user_id=user_id,
                        status="error", error_msg=str(e)[:200])
                break
            wait = min(10 * retry_count, 60)
            logger.warning(f"[IMWorker] error for {account_id[:8]}: {e}, retry in {wait}s")
            await asyncio.sleep(wait)

    _connections.pop(account_id, None)
    _active_listeners.pop(account_id, None)


def get_active_count() -> int:
    return len(_active_listeners)
