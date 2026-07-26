import { useIp } from "@oral/stores";
import type { Platform } from "@oral/types";
import { Info, TrendingDown, TrendingUp } from "lucide-react";
import PlatformIcon from "../components/PlatformIcon";

const STATS = [
  { k: "总播放", v: "28.6w", d: "+41% vs 上周", up: true },
  { k: "新增粉丝", v: "1,204", d: "+18% vs 上周", up: true },
  { k: "平均完播率", v: "34%", d: "-2% 需优化开头", up: false },
  { k: "发布条数", v: "21", d: "日更 3 条 · 全勤", up: true },
] as const;

const WEEK_BARS = [
  { day: "周一", h: 35 },
  { day: "周二", h: 48 },
  { day: "周三", h: 42 },
  { day: "周四", h: 66 },
  { day: "周五", h: 82 },
  { day: "周六", h: 100 },
  { day: "今天", h: 58 },
] as const;

const PLATFORM_SHARE: { platform: Platform; name: string; pct: number }[] = [
  { platform: "douyin", name: "抖音", pct: 52 },
  { platform: "xiaohongshu", name: "小红书", pct: 31 },
  { platform: "kuaishou", name: "快手", pct: 17 },
];

const TOP_VIDEOS = [
  { title: "新公司法 5 大变化", platform: "小红书", views: "21.7w 播放" },
  { title: "老板必看的 3 个节税思路", platform: "抖音", views: "12.4w 播放" },
  { title: "个体户报税全流程", platform: "快手", views: "8.2w 播放" },
] as const;

/** 数据看板（F-723 为 P1 能力，MVP 静态壳 + V1.1 占位） */
export default function AnalyticsPage() {
  const { current } = useIp();

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between rounded-card border border-info/30 bg-info/10 px-4 py-3 text-sm text-info">
        <span className="flex items-center gap-1.5">
          <Info className="h-4 w-4 shrink-0" />
          数据看板为 V1.1 能力（依赖平台数据回流核验 G3），以下为效果预览
        </span>
        <span className="chip border-info/40 text-info">V1.1 上线</span>
      </div>

      {/* 首屏：一个核心结论 */}
      <div className="glass-strong p-6">
        <div className="text-xs text-text-3">
          本周洞察 · IP：{current?.name ?? "—"} · 近 7 天
        </div>
        <h1 className="mt-2 text-2xl font-bold leading-snug">
          「节税」主题播放量是平均的 <span className="text-grad">3.2 倍</span>，
          <br className="hidden md:block" />
          建议下周加大该选题占比。
        </h1>
      </div>

      {/* 数据卡 */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {STATS.map((s) => (
          <div key={s.k} className="glass card-hover p-4">
            <div className="text-xs text-text-3">{s.k}</div>
            <div className="mt-1 text-2xl font-black">{s.v}</div>
            <div
              className={`mt-1 flex items-center gap-1 text-xs ${s.up ? "text-success" : "text-danger"}`}
            >
              {s.up ? (
                <TrendingUp className="h-3 w-3" />
              ) : (
                <TrendingDown className="h-3 w-3" />
              )}
              {s.d}
            </div>
          </div>
        ))}
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[1.4fr_1fr]">
        {/* 播放量趋势 */}
        <div className="glass p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-medium">播放量趋势</h2>
            <span className="text-xs text-text-3">按天 · 三平台合计</span>
          </div>
          <div className="flex h-44 items-end gap-3">
            {WEEK_BARS.map((b) => (
              <div
                key={b.day}
                className="flex flex-1 flex-col items-center gap-2"
              >
                <div className="flex h-36 w-full items-end rounded-lg bg-white/5">
                  <div
                    className="w-full rounded-lg bg-brand-grad-x"
                    style={{ height: `${b.h}%` }}
                  />
                </div>
                <span className="text-[11px] text-text-3">{b.day}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 平台分布 */}
        <div className="glass p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-medium">平台分布</h2>
            <span className="text-xs text-text-3">播放占比</span>
          </div>
          <div className="space-y-3.5">
            {PLATFORM_SHARE.map((p) => (
              <div key={p.name}>
                <div className="mb-1.5 flex justify-between text-xs">
                  <span className="flex items-center gap-1.5">
                    <PlatformIcon platform={p.platform} size={14} />
                    {p.name}
                  </span>
                  <span className="text-text-3">{p.pct}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
                  <div
                    className="h-full rounded-full bg-brand-grad-x"
                    style={{ width: `${p.pct}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-xl border border-info/30 bg-info/10 p-3 text-xs text-info">
            小红书「新公司法」单条播放 21.7w，完播率 41%，建议拆解为系列选题。
          </div>
        </div>
      </div>

      {/* TOP 视频 */}
      <div>
        <div className="mb-3 flex items-baseline gap-3">
          <h2 className="font-medium">本周 TOP 3 视频</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {TOP_VIDEOS.map((v) => (
            <div key={v.title} className="glass card-hover p-4">
              <div className="flex h-28 items-center justify-center rounded-lg bg-white/5 text-sm text-text-3">
                封面
              </div>
              <div className="mt-3 text-sm font-medium">{v.title}</div>
              <div className="mt-2 flex gap-1.5">
                <span className="chip text-[11px]">{v.platform}</span>
                <span className="chip border-success/40 text-[11px] text-success">
                  {v.views}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
