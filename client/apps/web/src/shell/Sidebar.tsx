import { pipelineApi, publishApi } from "@oral/api-client";
import { useIp, useQuota } from "@oral/stores";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  ChartColumn,
  Check,
  ChevronDown,
  CircleUserRound,
  Cloud,
  House,
  ListChecks,
  type LucideIcon,
  Mail,
  Music,
  PenLine,
  Send,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { NavLink, useNavigate } from "react-router";
import { ANALYTICS_PREVIEW, IM_ENABLED } from "../config/features";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  badge?: number;
  badgeTone?: "brand" | "danger";
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

/**
 * 左侧栏（对齐 05 文档 2.2 v1.1 迭代确认版）：
 * 一级导航精简为 7 项，按「做内容 → 养资产 → 发出去」分创作/资产/分发三组；
 * 一键成片为唯一高亮 CTA 不占导航位；声音/数字人/模板收敛为资产页 Tab 条二级导航；
 * 视频剪辑为流水线第⑥步不占一级位；套餐与积分收进算力卡。
 */
function buildNav(taskActive: number, publishFailed: number): NavGroup[] {
  return [
    {
      title: "创作",
      items: [
        { to: "/", label: "工作台", icon: House },
        { to: "/scripts", label: "文案工坊", icon: PenLine },
        {
          to: "/tasks",
          label: "任务中心",
          icon: ListChecks,
          badge: taskActive,
          badgeTone: "brand",
        },
      ],
    },
    {
      title: "资产",
      items: [
        { to: "/assets/personas", label: "IP 档案", icon: CircleUserRound },
        { to: "/assets/voices", label: "IP 声音", icon: Music },
        { to: "/assets/avatars", label: "IP 数字人", icon: Bot },
        // V1.1 未上架：素材库入口暂时隐藏，路由保留可直达；上线时恢复
        // { to: "/assets/materials", label: "素材库", icon: LayoutGrid },
      ],
    },
    {
      title: "分发",
      items: [
        {
          to: "/publish/jobs",
          label: "发布管理",
          icon: Send,
          badge: publishFailed,
          badgeTone: "danger",
        },
        ...(IM_ENABLED ? [{ to: "/im", label: "私信中心", icon: Mail }] : []),
        // V1.1 未上架：数据看板为演示数据占位页，生产构建默认隐藏入口（VITE_ANALYTICS_PREVIEW 开启）
        ...(ANALYTICS_PREVIEW
          ? [{ to: "/analytics", label: "数据看板", icon: ChartColumn }]
          : []),
      ],
    },
  ];
}

function IpSwitcher() {
  const { personas, current, switch: switchIp } = useIp();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="glass card-hover flex w-full items-center gap-3 px-3 py-2.5 text-left"
      >
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-base font-bold text-white"
          style={{
            background:
              current?.avatarGrad || "linear-gradient(135deg,#6366F1,#22D3EE)",
          }}
        >
          {current?.avatarChar || "IP"}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-text-1">
            {current?.name ?? "选择 IP"}
          </span>
          <span className="block truncate text-xs text-text-3">
            {current?.domain ?? "—"}
          </span>
        </span>
        <span className="text-text-3">
          <ChevronDown className="h-4 w-4" />
        </span>
      </button>
      {open && (
        <div className="glass-strong absolute left-0 right-0 top-full z-30 mt-2 overflow-hidden p-1">
          {personas.map((p) => (
            <button
              key={p.id}
              onClick={() => {
                setOpen(false);
                void switchIp(p.id);
              }}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-white/5 ${
                p.id === current?.id ? "text-brand-to" : "text-text-2"
              }`}
            >
              <span
                className="flex h-6 w-6 items-center justify-center rounded-lg text-xs font-bold text-white"
                style={{ background: p.avatarGrad }}
              >
                {p.avatarChar}
              </span>
              <span className="flex-1 truncate">{p.name}</span>
              {p.id === current?.id && <Check className="h-4 w-4" />}
            </button>
          ))}
          <button
            onClick={() => {
              setOpen(false);
              navigate("/assets/personas");
            }}
            className="w-full rounded-lg px-3 py-2 text-left text-xs text-text-3 hover:bg-white/5 hover:text-text-1"
          >
            + 管理 IP 档案
          </button>
        </div>
      )}
    </div>
  );
}

function QuotaCard() {
  const quota = useQuota((s) => s.quota);
  const balance = quota?.balance ?? 0;
  const total = quota?.total || 1;
  const pct = Math.min(100, Math.round((balance / total) * 100));
  return (
    <div className="glass px-3.5 py-3">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-xs text-text-2">
          <Cloud className="h-3.5 w-3.5" /> 云端算力 · 额度
        </span>
        <NavLink
          to="/pricing"
          title="套餐与积分"
          className="text-xs text-brand-to hover:underline"
        >
          套餐
        </NavLink>
      </div>
      <div className="mt-1 text-grad text-sm font-bold">
        {balance.toLocaleString()}
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/5">
        <div
          className="h-full rounded-full bg-brand-grad-x transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[11px] text-text-3">
        <span>剩余 {pct}%</span>
        <NavLink to="/pricing" className="text-brand-to hover:underline">
          充值/续费
        </NavLink>
      </div>
    </div>
  );
}

export default function Sidebar() {
  // 角标：任务中心=进行中任务数（执行中+待确认）；发布管理=待处理失败数（红）
  const { data: running } = useQuery({
    queryKey: ["nav-badge", "tasks-running"],
    queryFn: () => pipelineApi.list("running", 1, 1),
    refetchInterval: 30_000,
  });
  const { data: waiting } = useQuery({
    queryKey: ["nav-badge", "tasks-waiting"],
    queryFn: () => pipelineApi.list("waiting_confirm", 1, 1),
    refetchInterval: 30_000,
  });
  const { data: failedJobs } = useQuery({
    queryKey: ["nav-badge", "publish-failed"],
    queryFn: () => publishApi.jobs("failed", 1, 1),
    refetchInterval: 30_000,
  });
  const nav = buildNav(
    (running?.total ?? 0) + (waiting?.total ?? 0),
    failedJobs?.total ?? 0,
  );

  return (
    <aside className="flex w-60 shrink-0 flex-col gap-4 border-r border-stroke bg-black/20 px-4 py-5">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-1">
        <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-grad text-sm font-black text-white shadow-cta">
          口
        </span>
        <span className="text-base font-bold tracking-wide">
          口播<span className="text-grad">IP智能体</span>
        </span>
      </div>

      <IpSwitcher />

      {/* 一键成片 CTA */}
      <NavLink
        to="/create"
        className="btn-primary flex w-full items-center justify-center gap-1.5 py-2.5 text-base"
      >
        <Zap className="h-4 w-4" /> 一键成片
      </NavLink>

      {/* 导航分组 */}
      <nav className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        {nav.map((group) => (
          <div key={group.title}>
            <div className="mb-1 px-2 text-[11px] font-medium uppercase tracking-wider text-text-3">
              {group.title}
            </div>
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors ${
                      isActive
                        ? "border border-brand-from/30 bg-brand-from/15 text-text-1"
                        : "border border-transparent text-text-2 hover:bg-white/5 hover:text-text-1"
                    }`
                  }
                >
                  <span className="flex w-4 justify-center opacity-80">
                    <item.icon className="h-4 w-4" />
                  </span>
                  {item.label}
                  {item.badge ? (
                    <span
                      className={`ml-auto rounded-full px-1.5 py-px text-[10px] font-bold ${
                        item.badgeTone === "danger"
                          ? "bg-danger/20 text-danger"
                          : "bg-brand-from/25 text-brand-to"
                      }`}
                    >
                      {item.badge > 99 ? "99+" : item.badge}
                    </span>
                  ) : null}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <QuotaCard />
    </aside>
  );
}
