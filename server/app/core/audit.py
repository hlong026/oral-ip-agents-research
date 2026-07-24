"""
安全审计日志 DB 双写（06 文档 §10.6.7）
- A 类安全/资金/故障事件必须持久化到 audit_logs 表
- 异步写入，不阻塞主业务流程
- 与 structlog stdout 日志互为补充（stdout 用于实时告警，DB 用于合规追溯）
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SessionLocal


def _new_id() -> str:
    return uuid.uuid4().hex


class AuditLog(Base):
    """安全审计日志表（不可删除、不可修改，仅追加）"""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    event: Mapped[str] = mapped_column(String(64), index=True)  # 事件名：user_login / quota_charged 等
    user_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    trace_id: Mapped[str] = mapped_column(String(32), default="")
    task_id: Mapped[str] = mapped_column(String(32), default="")
    detail: Mapped[str] = mapped_column(Text, default="")  # JSON 格式附加信息
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


async def write_audit(
    event: str, *, user_id: str = "", trace_id: str = "", task_id: str = "", detail: str = ""
) -> None:
    """
    异步写入审计日志（fire-and-forget，失败仅记 warning 不影响主流程）
    使用独立 Session 避免与业务事务耦合。
    """
    from app.core.logging import get_logger, trace_id_var

    logger = get_logger("oral.audit")
    try:
        async with SessionLocal() as db:
            db.add(
                AuditLog(
                    event=event,
                    user_id=user_id,
                    trace_id=trace_id or trace_id_var.get(""),
                    task_id=task_id,
                    detail=detail[:2000],
                )
            )
            await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("audit_write_failed", audit_event=event, error=str(e)[:200])


def add_audit(
    db,
    event: str,
    *,
    user_id: str = "",
    trace_id: str = "",
    task_id: str = "",
    detail: str = "",
) -> None:
    """同事务追加审计日志（资金/权限类 A 级事件）。

    将审计记录挂入调用方传入的业务 Session：业务事务提交时审计一并落库，
    业务回滚时审计随之消失，保证"无业务结果即无审计、有业务结果必有审计"，
    避免 fire-and-forget 路径在 DB 抖动时丢失资金类合规证据。
    """
    from app.core.logging import trace_id_var

    db.add(
        AuditLog(
            event=event,
            user_id=user_id,
            trace_id=trace_id or trace_id_var.get(""),
            task_id=task_id,
            detail=detail[:2000],
        )
    )
