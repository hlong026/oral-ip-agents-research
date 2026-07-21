"""开发环境激活码生成脚本

用法：
  cd server
  python -m scripts_gen_dev_codes [--count 5] [--plan monthly] [--quota 5000] [--days 30]

生成的码会直接打印到控制台，同时写入 DB（需服务已启动或手动初始化 DB）。
也可纯离线生成（不写 DB）：加 --offline 参数。
"""

import argparse
import asyncio
import sys
from pathlib import Path

# 确保 server 目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def gen_offline(count: int, plan_type: str, quota: float, days: int) -> list[str]:
    """纯离线生成（不写 DB，仅打印码）"""
    from app.modules.activation.code_generator import generate_batch

    codes = generate_batch(count)
    return codes


async def gen_with_db(count: int, plan_type: str, quota: float, days: int, channel: str) -> None:
    """写入 DB（需先初始化数据库）"""
    from app.core.db import SessionLocal, init_models
    from app.modules.activation import service

    await init_models()
    async with SessionLocal() as db:
        result = await service.generate_batch(
            db,
            name=f"开发环境-{plan_type}×{count}",
            plan_type=plan_type,
            quota_amount=quota,
            duration_days=days,
            count=count,
            channel=channel,
            code_expires_at=None,
            created_by="dev-script",
        )
        print(f"\n✅ 已生成 {result.generated} 个激活码（批次 ID: {result.batchId}）")
        print(f"   套餐: {plan_type} | 额度: {quota} | 有效期: {days} 天")
        print("\n" + "=" * 50)
        for i, code in enumerate(result.codes, 1):
            print(f"  {i:3d}. {code}")
        print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="开发环境激活码生成")
    parser.add_argument("--count", type=int, default=5, help="生成数量（默认 5）")
    parser.add_argument(
        "--plan",
        default="monthly",
        choices=["trial", "monthly", "quarterly", "yearly", "points"],
        help="套餐类型（默认 monthly）",
    )
    parser.add_argument("--quota", type=float, default=5000, help="额度点数（默认 5000）")
    parser.add_argument("--days", type=int, default=30, help="有效天数（默认 30，0=永久）")
    parser.add_argument("--channel", default="dev", help="渠道标识（默认 dev）")
    parser.add_argument("--offline", action="store_true", help="纯离线生成（不写 DB）")
    args = parser.parse_args()

    print("🔑 激活码生成器（开发环境）")
    print(f"   套餐: {args.plan} | 额度: {args.quota} | 有效期: {args.days} 天 | 数量: {args.count}")
    print()

    if args.offline:
        codes = gen_offline(args.count, args.plan, args.quota, args.days)
        print("=" * 50)
        for i, code in enumerate(codes, 1):
            print(f"  {i:3d}. {code}")
        print("=" * 50)
        print("\n⚠️  离线模式：码未写入数据库，需通过管理 API 导入后才能使用")
    else:
        asyncio.run(gen_with_db(args.count, args.plan, args.quota, args.days, args.channel))


if __name__ == "__main__":
    main()
