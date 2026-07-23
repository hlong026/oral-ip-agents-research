import { useQuery } from "@tanstack/react-query";
import { adminApi } from "../lib/adminHttp";

/** 数字格式化：千分位 */
function fmt(n: number): string {
  return n.toLocaleString("zh-CN");
}

export default function OverviewPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-overview"],
    queryFn: adminApi.overview,
    refetchInterval: 60_000,
  });

  const cards = [
    {
      label: "总用户数",
      value: data ? fmt(data.totalUsers) : "-",
      desc: data ? `今日新增 ${fmt(data.newUsersToday)} 人` : "激活码开户用户总量",
    },
    {
      label: "任务总量",
      value: data ? fmt(data.totalTasks) : "-",
      desc: data ? `今日完成 ${fmt(data.doneTasksToday)} 条` : "创作管线任务总数",
    },
    {
      label: "激活码",
      value: data ? fmt(data.totalCodes) : "-",
      desc: data
        ? `已消耗 ${fmt(data.usedCodes)}（消耗率 ${
            data.totalCodes > 0
              ? Math.round((data.usedCodes / data.totalCodes) * 100)
              : 0
          }%）`
        : "批次生成与兑换追踪",
    },
    {
      label: "积分发放",
      value: data ? fmt(data.totalGranted) : "-",
      desc: data ? `已消耗 ${fmt(data.totalConsumed)} 积分` : "套餐/充值/调整累计发放",
    },
  ];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">运营总览</h1>
        <p className="mt-2 text-sm text-text-3">
          核心运营指标实时聚合，每分钟自动刷新。
        </p>
      </div>

      {error && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          指标加载失败，请检查管理端服务状态后重试。
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <section key={card.label} className="glass p-5">
            <p className="text-sm text-text-3">{card.label}</p>
            <p className="mt-3 text-xl font-semibold">
              {isLoading ? "…" : card.value}
            </p>
            <p className="mt-2 text-sm text-text-3">{card.desc}</p>
          </section>
        ))}
      </div>

      {/* 订阅到期预警 */}
      <section className="glass p-5">
        <div className="flex items-center justify-between">
          <h2 className="font-medium">订阅到期预警</h2>
          {data && data.expiringSubscriptions > 0 && (
            <span className="rounded-full border border-warning/40 px-3 py-1 text-xs text-warning">
              需跟进
            </span>
          )}
        </div>
        <p className="mt-3 text-sm text-text-2">
          {isLoading
            ? "统计中…"
            : data
              ? `未来 7 天内有 ${fmt(data.expiringSubscriptions)} 名用户的订阅即将到期，可提前触达续费。`
              : "暂无数据"}
        </p>
      </section>

      <section className="glass p-5">
        <h2 className="font-medium">上线前检查</h2>
        <ul className="mt-3 grid gap-2 text-sm text-text-2 md:grid-cols-2">
          <li>普通用户不能访问 `/api/admin/v1/*`。</li>
          <li>激活码批次只能绑定已发布 SKU 版本。</li>
          <li>用户端只展示公开 SKU 和公开积分价格。</li>
          <li>Provider 密钥只在管理端配置，不进入用户端构建产物。</li>
        </ul>
      </section>
    </div>
  );
}
