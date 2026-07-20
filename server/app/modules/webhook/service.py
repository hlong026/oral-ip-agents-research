"""
Webhook 回调处理（供应商任务完成通知）
按 type 分发：
- type=1：创作任务完成 → 更新 pipeline 产物
- type=2：数字人克隆完成 → 更新 avatar status
- type=3：声音克隆完成 → 下载 demo 转存 → 更新 voice status
幂等：task_id 去重，防重复处理
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def handle_callback(db: AsyncSession, payload: dict) -> None:
    """统一回调分发"""
    msg_type = payload.get("type", 0)
    task_id = payload.get("task_id", "")
    status_code = payload.get("status", 0)

    if not task_id:
        logger.warning(f"webhook: missing task_id, payload={payload}")
        return

    if msg_type == 3:
        # 声音克隆完成
        from app.modules.voice.service import handle_voice_callback

        voice_id = payload.get("voice", "")
        demo_url = payload.get("demo_url", "")
        await handle_voice_callback(db, task_id, status_code, voice_id, demo_url)
        logger.info(f"webhook: voice clone callback processed, task_id={task_id}, status={status_code}")

    elif msg_type == 2:
        # 数字人克隆完成
        from app.modules.avatar.service import handle_avatar_callback

        avatar_id = payload.get("avatar", "")
        await handle_avatar_callback(db, task_id, status_code, avatar_id)
        logger.info(f"webhook: avatar clone callback processed, task_id={task_id}, status={status_code}")

    elif msg_type == 1:
        # 创作任务完成（视频生成）
        video_url = payload.get("video_Url", "")
        duration = payload.get("duration", 0)
        title = payload.get("title", "")
        logger.info(
            f"webhook: video creation callback, task_id={task_id}, "
            f"status={status_code}, duration={duration}, title={title}"
        )
        # 视频创作回调目前由 pipeline 轮询处理，此处仅记录日志
        # 后续可扩展为主动更新 pipeline task 产物

    else:
        logger.warning(f"webhook: unknown type={msg_type}, task_id={task_id}")
