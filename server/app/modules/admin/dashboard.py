"""运营总览驾驶舱聚合：六大业务块按天时间序列，一次请求全量返回。

聚合口径：
- 运营日界按 Asia/Shanghai 划分（数据库统一存 UTC）
- 序列在 Python 侧分桶，规避 sqlite/postgres 日期函数方言差异
- 成本为估算值：用量积分 / 模块积分单价 × 内部成本单价（无运行时成本流水表）
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activation.models import ActivationCode, UserSubscription
from app.modules.auth.models import User
from app.modules.avatar.models import Avatar
from app.modules.billing.models import CreditGrant, QuotaUsage
from app.modules.catalog import repository as catalog_repo
from app.modules.catalog.models import PlanSkuVersion
from app.modules.pipeline.models import PipelineTask
from app.modules.publish.models import PublishJob
from app.modules.voice.models import Voice

OPS_TZ = ZoneInfo("Asia/Shanghai")

# 计量步骤 → 价格目录模块（用于成本估算；无映射的步骤不计成本）
STEP_TO_MODULE = {
    "parse": "topic_generation",
    "topic_generation": "topic_generation",
    "asr": "asr",
    "rewrite": "script_generation",
    "script_generation": "script_generation",
    "voice": "tts",
    "tts": "tts",
    "voice_clone": "voice_clone",
    "avatar": "digital_human",
    "digital_human": "digital_human",
    "compose": "hd_export",
    "hd_export": "hd_export",
}


def _as_utc(value: datetime) -> datetime:
    """sqlite 会丢失 tzinfo（值本身是 UTC），统一补齐后再换算运营时区。"""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _day_key(value: datetime) -> str:
    return _as_utc(value).astimezone(OPS_TZ).date().isoformat()


def _bucket_counts(dates: list[str], stamps: Iterable[datetime]) -> list[int]:
    buckets: dict[str, int] = defaultdict(int)
    for stamp in stamps:
        buckets[_day_key(stamp)] += 1
    return [buckets[day] for day in dates]


def _bucket_sums(dates: list[str], rows: Iterable[tuple[datetime, float]]) -> list[float]:
    buckets: dict[str, float] = defaultdict(float)
    for stamp, value in rows:
        buckets[_day_key(stamp)] += float(value)
    return [round(buckets[day], 2) for day in dates]


async def build_dashboard(db: AsyncSession, days: int) -> dict:
    today = datetime.now(OPS_TZ).date()
    day_list: list[date] = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    dates = [day.isoformat() for day in day_list]
    window_start = datetime.combine(day_list[0], time.min, tzinfo=OPS_TZ).astimezone(UTC)

    # ---- 用户 ----
    total_users = int((await db.execute(select(func.count(User.id)))).scalar() or 0)
    user_stamps = (await db.execute(select(User.created_at).where(User.created_at >= window_start))).scalars().all()
    new_users = _bucket_counts(dates, user_stamps)
    cumulative_users: list[int] = []
    running = total_users - len(user_stamps)
    for count in new_users:
        running += count
        cumulative_users.append(running)

    # ---- 激活码 ----
    code_created_stamps = (
        (await db.execute(select(ActivationCode.created_at).where(ActivationCode.created_at >= window_start)))
        .scalars()
        .all()
    )
    code_activated_stamps = (
        (await db.execute(select(ActivationCode.activated_at).where(ActivationCode.activated_at >= window_start)))
        .scalars()
        .all()
    )
    codes_unused = int(
        (await db.execute(select(func.count(ActivationCode.id)).where(ActivationCode.status == "unused"))).scalar() or 0
    )
    codes_activated_total = int(
        (
            await db.execute(select(func.count(ActivationCode.id)).where(ActivationCode.bound_user_id.is_not(None)))
        ).scalar()
        or 0
    )

    # ---- 积分经济 ----
    grant_rows = (
        await db.execute(
            select(CreditGrant.created_at, CreditGrant.granted_points).where(CreditGrant.created_at >= window_start)
        )
    ).all()
    usage_rows = (
        await db.execute(
            select(QuotaUsage.created_at, QuotaUsage.step, QuotaUsage.points).where(
                QuotaUsage.created_at >= window_start
            )
        )
    ).all()
    points_granted = _bucket_sums(dates, [(stamp, points) for stamp, points in grant_rows])
    # QuotaUsage 正数为扣减、负数为退还，净值即当日实际消耗
    points_consumed = _bucket_sums(dates, [(stamp, points) for stamp, _step, points in usage_rows])

    # ---- 生产任务 ----
    task_created_stamps = (
        (await db.execute(select(PipelineTask.created_at).where(PipelineTask.created_at >= window_start)))
        .scalars()
        .all()
    )
    task_done_stamps = (
        (
            await db.execute(
                select(PipelineTask.updated_at).where(
                    PipelineTask.status == "done", PipelineTask.updated_at >= window_start
                )
            )
        )
        .scalars()
        .all()
    )
    task_failed_stamps = (
        (
            await db.execute(
                select(PipelineTask.updated_at).where(
                    PipelineTask.status == "failed", PipelineTask.updated_at >= window_start
                )
            )
        )
        .scalars()
        .all()
    )
    voice_clone_stamps = (
        (await db.execute(select(Voice.created_at).where(Voice.source == "clone", Voice.created_at >= window_start)))
        .scalars()
        .all()
    )
    avatar_stamps = (
        (await db.execute(select(Avatar.created_at).where(Avatar.created_at >= window_start))).scalars().all()
    )

    # ---- 发布分发 ----
    publish_created_stamps = (
        (await db.execute(select(PublishJob.created_at).where(PublishJob.created_at >= window_start))).scalars().all()
    )
    publish_success_stamps = (
        (
            await db.execute(
                select(PublishJob.updated_at).where(
                    PublishJob.status == "success", PublishJob.updated_at >= window_start
                )
            )
        )
        .scalars()
        .all()
    )
    publish_failed_stamps = (
        (
            await db.execute(
                select(PublishJob.updated_at).where(
                    PublishJob.status == "failed", PublishJob.updated_at >= window_start
                )
            )
        )
        .scalars()
        .all()
    )

    # ---- 成本毛利 ----
    # 收入（现金口径）：窗口内激活的订阅 × 对应 SKU 版本展示价
    subscription_rows = (
        await db.execute(
            select(UserSubscription.activated_at, UserSubscription.sku_version_id).where(
                UserSubscription.activated_at >= window_start
            )
        )
    ).all()
    sku_version_ids = {version_id for _stamp, version_id in subscription_rows if version_id}
    price_by_version: dict[str, int] = {}
    if sku_version_ids:
        version_rows = (
            await db.execute(
                select(PlanSkuVersion.id, PlanSkuVersion.display_price_cents).where(
                    PlanSkuVersion.id.in_(sku_version_ids)
                )
            )
        ).all()
        price_by_version = {version_id: cents for version_id, cents in version_rows}
    revenue_cents = _bucket_sums(
        dates,
        [(stamp, price_by_version.get(version_id, 0)) for stamp, version_id in subscription_rows],
    )

    # 成本（估算口径）：用量积分 / 模块积分单价 × 内部成本单价
    cost_per_point: dict[str, float] = {}
    active_version = await catalog_repo.active_price_version(db)
    if active_version is not None:
        for price in await catalog_repo.all_module_prices(db, active_version.id):
            if price.points_per_unit > 0 and price.internal_cost_cents_per_unit > 0:
                cost_per_point[price.module] = price.internal_cost_cents_per_unit / price.points_per_unit
    cost_cents = _bucket_sums(
        dates,
        [
            (stamp, points * cost_per_point.get(STEP_TO_MODULE.get(step, ""), 0.0))
            for stamp, step, points in usage_rows
            if points > 0
        ],
    )

    tasks_created = _bucket_counts(dates, task_created_stamps)
    publish_succeeded = _bucket_counts(dates, publish_success_stamps)
    publish_failed = _bucket_counts(dates, publish_failed_stamps)
    publish_finished = sum(publish_succeeded) + sum(publish_failed)

    def _today_pair(series: list[float] | list[int]) -> tuple[float, float]:
        current = series[-1] if series else 0
        previous = series[-2] if len(series) > 1 else 0
        return float(current), float(previous)

    new_today, new_yesterday = _today_pair(new_users)
    consumed_today, consumed_yesterday = _today_pair(points_consumed)
    tasks_today, tasks_yesterday = _today_pair(tasks_created)

    return {
        "rangeDays": days,
        "generatedAt": datetime.now(UTC).isoformat(),
        "dates": dates,
        "kpis": {
            "totalUsers": total_users,
            "newUsersToday": int(new_today),
            "newUsersYesterday": int(new_yesterday),
            "pointsConsumedToday": consumed_today,
            "pointsConsumedYesterday": consumed_yesterday,
            "tasksCreatedToday": int(tasks_today),
            "tasksCreatedYesterday": int(tasks_yesterday),
            "publishSuccessRate": (round(sum(publish_succeeded) / publish_finished, 4) if publish_finished else None),
            "codesUnused": codes_unused,
            "codesActivatedTotal": codes_activated_total,
            "revenueCentsWindow": round(sum(revenue_cents), 2),
            "costCentsWindow": round(sum(cost_cents), 2),
        },
        "users": {
            "newUsers": new_users,
            "cumulativeUsers": cumulative_users,
        },
        "activation": {
            "created": _bucket_counts(dates, code_created_stamps),
            "activated": _bucket_counts(dates, (stamp for stamp in code_activated_stamps if stamp is not None)),
        },
        "credits": {
            "granted": points_granted,
            "consumed": points_consumed,
        },
        "production": {
            "tasksCreated": tasks_created,
            "tasksSucceeded": _bucket_counts(dates, task_done_stamps),
            "tasksFailed": _bucket_counts(dates, task_failed_stamps),
            "voiceClones": _bucket_counts(dates, voice_clone_stamps),
            "avatarTrainings": _bucket_counts(dates, avatar_stamps),
        },
        "publishing": {
            "created": _bucket_counts(dates, publish_created_stamps),
            "succeeded": publish_succeeded,
            "failed": publish_failed,
        },
        "economics": {
            "revenueCents": revenue_cents,
            "costCents": cost_cents,
        },
    }
