import { useQuery } from "@tanstack/react-query";
import { graphic } from "echarts/core";
import { TrendingDown, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import DashboardChart, { type ChartOption } from "../components/DashboardChart";
import { adminApi, type DashboardOut } from "@oral/admin-api-client";

/** 设计令牌同步（tailwind.preset.ts），图表配色与全站一致 */
const C = {
  brand: "#6366F1",
  cyan: "#22D3EE",
  success: "#34D399",
  danger: "#F87171",
  warning: "#FBBF24",
  info: "#60A5FA",
  text2: "#9CA3AF",
  text3: "#6B7280",
  splitLine: "rgba(255,255,255,0.06)",
  axisLine: "rgba(255,255,255,0.12)",
};

const RANGE_OPTIONS = [
  { days: 7, label: "近 7 天" },
  { days: 30, label: "近 30 天" },
  { days: 90, label: "近 90 天" },
];

function baseOption(dates: string[]): ChartOption {
  return {
    backgroundColor: "transparent",
    legend: {
      top: 0,
      left: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 14,
      textStyle: { color: C.text2, fontSize: 11 },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(17,24,39,0.94)",
      borderColor: "rgba(255,255,255,0.14)",
      textStyle: { color: "#E5E7EB", fontSize: 12 },
      axisPointer: { lineStyle: { color: "rgba(255,255,255,0.2)" } },
    },
    grid: { left: 4, right: 8, top: 34, bottom: 0, containLabel: true },
    xAxis: {
      type: "category",
      boundaryGap: true,
      data: dates.map((d) => d.slice(5)),
      axisLine: { lineStyle: { color: C.axisLine } },
      axisTick: { show: false },
      axisLabel: { color: C.text3, fontSize: 10 },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: C.splitLine } },
      axisLabel: { color: C.text3, fontSize: 10 },
    },
  };
}

/** 发光曲线 + 渐隐面积，大屏质感的核心笔触 */
function glowLine(
  name: string,
  data: number[],
  color: string,
  { area = false }: { area?: boolean } = {},
) {
  return {
    name,
    type: "line" as const,
    smooth: true,
    symbol: "none",
    data,
    lineStyle: { width: 2, color, shadowColor: color, shadowBlur: 10 },
    itemStyle: { color },
    emphasis: { focus: "series" as const },
    ...(area
      ? {
          areaStyle: {
            opacity: 1,
            color: new graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: `${color}38` },
              { offset: 1, color: `${color}00` },
            ]),
          },
        }
      : {}),
  };
}

function bar(
  name: string,
  data: number[],
  color: string,
  { stack }: { stack?: string } = {},
) {
  return {
    name,
    type: "bar" as const,
    data,
    stack,
    barMaxWidth: 14,
    itemStyle: { color, borderRadius: stack ? 0 : [3, 3, 0, 0] },
    emphasis: { focus: "series" as const },
  };
}

const yuanTooltip = {
  valueFormatter: (value: unknown) =>
    `¥${(Number(value ?? 0) / 100).toFixed(2)}`,
};

function buildOptions(data: DashboardOut) {
  const base = () => baseOption(data.dates);

  const users: ChartOption = {
    ...base(),
    yAxis: [
      {
        type: "value",
        splitLine: { lineStyle: { color: C.splitLine } },
        axisLabel: { color: C.text3, fontSize: 10 },
      },
      {
        type: "value",
        splitLine: { show: false },
        axisLabel: { color: C.text3, fontSize: 10 },
      },
    ],
    series: [
      bar("每日新增", data.users.newUsers, C.brand),
      {
        ...glowLine("累计用户", data.users.cumulativeUsers, C.cyan, {
          area: true,
        }),
        yAxisIndex: 1,
      },
    ],
  };

  const credits: ChartOption = {
    ...base(),
    series: [
      glowLine("积分发放", data.credits.granted, C.success, { area: true }),
      glowLine("积分消耗", data.credits.consumed, C.danger, { area: true }),
    ],
  };

  const production: ChartOption = {
    ...base(),
    series: [
      bar("成功", data.production.tasksSucceeded, C.success, {
        stack: "tasks",
      }),
      bar("失败", data.production.tasksFailed, C.danger, { stack: "tasks" }),
      glowLine("新建任务", data.production.tasksCreated, C.info),
    ],
  };

  const training: ChartOption = {
    ...base(),
    series: [
      glowLine("声音克隆", data.production.voiceClones, C.brand, {
        area: true,
      }),
      glowLine("数字人训练", data.production.avatarTrainings, C.cyan, {
        area: true,
      }),
    ],
  };

  const publishing: ChartOption = {
    ...base(),
    series: [
      bar("成功", data.publishing.succeeded, C.success, { stack: "publish" }),
      bar("失败", data.publishing.failed, C.danger, { stack: "publish" }),
      glowLine("新建发布", data.publishing.created, C.info),
    ],
  };

  const activation: ChartOption = {
    ...base(),
    series: [
      bar("生成", data.activation.created, C.info),
      glowLine("激活", data.activation.activated, C.warning, { area: true }),
    ],
  };

  const economics: ChartOption = {
    ...base(),
    tooltip: { ...(base().tooltip as object), ...yuanTooltip },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: C.splitLine } },
      axisLabel: {
        color: C.text3,
        fontSize: 10,
        formatter: (value: number) => `¥${(value / 100).toFixed(0)}`,
      },
    },
    series: [
      glowLine("激活收入", data.economics.revenueCents, C.success, {
        area: true,
      }),
      glowLine("估算成本", data.economics.costCents, C.danger, { area: true }),
    ],
  };

  return {
    users,
    credits,
    production,
    training,
    publishing,
    activation,
    economics,
  };
}

function Delta({ current, previous }: { current: number; previous: number }) {
  const diff = current - previous;
  if (diff === 0)
    return <span className="text-xs text-text-3">与昨日持平</span>;
  const up = diff > 0;
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${up ? "text-success" : "text-danger"}`}
    >
      {up ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
      {up ? "+" : ""}
      {Number.isInteger(diff) ? diff : diff.toFixed(1)} vs 昨日
    </span>
  );
}

function KpiCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub: React.ReactNode;
}) {
  return (
    <section className="glass px-4 py-3.5">
      <p className="text-xs text-text-3">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight">
        {value}
      </p>
      <div className="mt-1">{sub}</div>
    </section>
  );
}

function ChartCard({
  title,
  subtitle,
  className = "",
  children,
}: {
  title: string;
  subtitle: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`glass p-4 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-medium">{title}</h2>
        <p className="text-xs text-text-3">{subtitle}</p>
      </div>
      {children}
    </section>
  );
}

const yuan = (cents: number) => `¥${(cents / 100).toFixed(2)}`;

export default function OverviewPage() {
  const [days, setDays] = useState(30);
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["admin-dashboard", days],
    queryFn: () => adminApi.dashboard(days),
    refetchInterval: 60_000, // 大盘数据每分钟自动刷新
  });

  const options = useMemo(() => (data ? buildOptions(data) : null), [data]);
  const kpis = data?.kpis;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">运营总览</h1>
          <p className="mt-2 text-sm text-text-3">
            六大业务模型的实时大盘：用户、激活码、积分经济、生产任务、发布分发与成本毛利。
          </p>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <span className="text-xs text-text-3">
              更新于 {new Date(data.generatedAt).toLocaleTimeString("zh-CN")}
            </span>
          )}
          <div className="flex rounded-xl border border-stroke bg-white/5 p-0.5">
            {RANGE_OPTIONS.map((range) => (
              <button
                key={range.days}
                onClick={() => setDays(range.days)}
                className={`rounded-[10px] px-3 py-1.5 text-xs transition ${
                  days === range.days
                    ? "bg-white/10 text-white"
                    : "text-text-3 hover:text-text-1"
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isError && (
        <section className="glass flex items-center justify-between p-5">
          <p className="text-sm text-danger">大盘数据加载失败，请重试。</p>
          <button className="btn-ghost" onClick={() => refetch()}>
            重新加载
          </button>
        </section>
      )}

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="glass h-24 animate-pulse" />
          ))}
        </div>
      )}

      {kpis && (
        <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
          <KpiCard
            label="总用户"
            value={String(kpis.totalUsers)}
            sub={
              <span className="text-xs text-text-3">
                今日 +{kpis.newUsersToday}
              </span>
            }
          />
          <KpiCard
            label="今日新增用户"
            value={String(kpis.newUsersToday)}
            sub={
              <Delta
                current={kpis.newUsersToday}
                previous={kpis.newUsersYesterday}
              />
            }
          />
          <KpiCard
            label="今日消耗积分"
            value={String(kpis.pointsConsumedToday)}
            sub={
              <Delta
                current={kpis.pointsConsumedToday}
                previous={kpis.pointsConsumedYesterday}
              />
            }
          />
          <KpiCard
            label="今日新建任务"
            value={String(kpis.tasksCreatedToday)}
            sub={
              <Delta
                current={kpis.tasksCreatedToday}
                previous={kpis.tasksCreatedYesterday}
              />
            }
          />
          <KpiCard
            label="发布成功率"
            value={
              kpis.publishSuccessRate == null
                ? "—"
                : `${(kpis.publishSuccessRate * 100).toFixed(1)}%`
            }
            sub={<span className="text-xs text-text-3">窗口内已完结任务</span>}
          />
          <KpiCard
            label="窗口激活收入"
            value={yuan(kpis.revenueCentsWindow)}
            sub={
              <span className="text-xs text-text-3">
                估算成本 {yuan(kpis.costCentsWindow)} · 待用码{" "}
                {kpis.codesUnused}
              </span>
            }
          />
        </div>
      )}

      {isLoading && (
        <div className="grid gap-4 xl:grid-cols-6">
          <div className="glass h-72 animate-pulse xl:col-span-4" />
          <div className="glass h-72 animate-pulse xl:col-span-2" />
          <div className="glass h-64 animate-pulse xl:col-span-2" />
          <div className="glass h-64 animate-pulse xl:col-span-2" />
          <div className="glass h-64 animate-pulse xl:col-span-2" />
        </div>
      )}

      {options && (
        <div className="grid gap-4 xl:grid-cols-6">
          <ChartCard
            title="用户增长"
            subtitle="每日新增 / 累计用户"
            className="xl:col-span-4"
          >
            <DashboardChart
              option={options.users}
              height={280}
              ariaLabel="用户增长趋势图"
            />
          </ChartCard>
          <ChartCard
            title="积分经济"
            subtitle="发放 vs 消耗"
            className="xl:col-span-2"
          >
            <DashboardChart
              option={options.credits}
              height={280}
              ariaLabel="积分发放与消耗趋势图"
            />
          </ChartCard>
          <ChartCard
            title="生产任务"
            subtitle="新建 / 成功 / 失败"
            className="xl:col-span-2"
          >
            <DashboardChart
              option={options.production}
              ariaLabel="生产任务趋势图"
            />
          </ChartCard>
          <ChartCard
            title="克隆与训练"
            subtitle="声音克隆 / 数字人训练"
            className="xl:col-span-2"
          >
            <DashboardChart
              option={options.training}
              ariaLabel="声音克隆与数字人训练趋势图"
            />
          </ChartCard>
          <ChartCard
            title="发布分发"
            subtitle="新建 / 成功 / 失败"
            className="xl:col-span-2"
          >
            <DashboardChart
              option={options.publishing}
              ariaLabel="发布分发趋势图"
            />
          </ChartCard>
          <ChartCard
            title="成本毛利"
            subtitle="激活收入 vs 估算供应商成本"
            className="xl:col-span-3"
          >
            <DashboardChart
              option={options.economics}
              ariaLabel="收入与成本趋势图"
            />
          </ChartCard>
          <ChartCard
            title="激活码"
            subtitle="每日生成 / 激活"
            className="xl:col-span-3"
          >
            <DashboardChart
              option={options.activation}
              ariaLabel="激活码生成与激活趋势图"
            />
          </ChartCard>
        </div>
      )}
    </div>
  );
}
