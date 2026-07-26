import {
  contentApi,
  dashboardApi,
  HttpError,
  pipelineApi,
} from "@oral/api-client";
import { useRelativeTime } from "@oral/hooks";
import { useIp, useTasks } from "@oral/stores";
import { STEP_LABELS, type PipelineTask } from "@oral/types";
import { useQuery } from "@tanstack/react-query";
import {
  type LucideIcon,
  Music,
  PenLine,
  Send,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import LinkSourceInput from "../components/LinkSourceInput";
import TaskCard from "../components/TaskCard";
import {
  confirmMeteredOperation,
  mediaDurationSeconds,
} from "../lib/meteredOperation";

/** Hero 大输入框（链接/选题 → 提取文案入工坊 / 一键成片双入口，平台自动识别） */
function HeroInput() {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<"parse" | "upload" | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const isUrl = /^https?:\/\//i.test(value.trim());

  /** 开始创作：链接/选题带入一键成片向导 */
  const goCreate = () => {
    if (!value.trim()) return;
    navigate(
      isUrl
        ? `/create?step=link&url=${encodeURIComponent(value.trim())}`
        : `/create?step=link&topic=${encodeURIComponent(value.trim())}`,
    );
  };

  /** 提取文案：解析落库后跳文案工坊详情，带入本次文案 */
  const goExtract = async (url?: string, file?: File) => {
    setBusy(file ? "upload" : "parse");
    setError("");
    try {
      const seconds = file
        ? await mediaDurationSeconds(file)
        : (await contentApi.probe(url ?? "")).durationSeconds;
      const quoteId = await confirmMeteredOperation("asr", "提取文案", {
        seconds,
        assets: 1,
      });
      if (!quoteId) return;
      const res = await contentApi.parse(url, file, quoteId);
      if (res.scriptId) {
        navigate(`/scripts/${res.scriptId}`);
      } else {
        setError("解析失败，可重试或改上传本地文件");
      }
    } catch (e) {
      setError(e instanceof HttpError ? e.body.message : "解析失败，请重试");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="glass-strong relative overflow-hidden p-6">
      <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand-from/20 blur-3xl" />
      <h1 className="text-2xl font-bold">
        粘贴爆款链接，<span className="text-grad">30 秒</span>复刻你的口播视频
      </h1>
      <p className="mt-1.5 text-sm text-text-3">
        支持抖音 / 小红书 / B站链接，或直接输入选题
      </p>
      <div className="mt-4 flex gap-2">
        <div className="flex-1">
          <LinkSourceInput
            value={value}
            onChange={setValue}
            onUpload={(f) => void goExtract(undefined, f)}
            uploading={busy === "upload"}
            placeholder="粘贴视频链接，或输入选题（如：个体户报税 3 个坑）…"
            inputClassName="h-12 text-base"
            onEnter={isUrl ? () => void goExtract(value.trim()) : goCreate}
          />
        </div>
        {isUrl && (
          <button
            onClick={() => void goExtract(value.trim())}
            disabled={busy !== null}
            className="btn-ghost h-12 shrink-0 px-5 text-base"
          >
            {busy === "parse" ? "提取中…" : "提取文案"}
          </button>
        )}
        <button
          onClick={goCreate}
          disabled={!value.trim() || busy !== null}
          className="btn-primary h-12 shrink-0 px-6 text-base"
        >
          开始创作 →
        </button>
      </div>
      {error && <div className="mt-2 text-sm text-danger">{error}</div>}
    </div>
  );
}

function StatCards() {
  const { data } = useQuery({
    queryKey: ["overview"],
    queryFn: () => dashboardApi.overview(),
  });
  const cards = [
    {
      label: "今日成片",
      value: data?.todayDone ?? 0,
      delta: data?.todayDelta,
      suffix: "条",
    },
    { label: "队列中", value: data?.queued ?? 0, suffix: "个任务" },
    {
      label: "本周发布",
      value: data?.published ?? 0,
      delta: data?.weekDelta,
      suffix: "条",
    },
    {
      label: "待处理告警",
      value: data?.pendingAlerts ?? 0,
      warn: (data?.pendingAlerts ?? 0) > 0,
      suffix: "条",
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
      {cards.map((c) => (
        <div key={c.label} className="glass card-hover p-4">
          <div className="text-xs text-text-3">{c.label}</div>
          <div
            className={`mt-1 text-2xl font-black ${c.warn ? "text-danger" : ""}`}
          >
            {c.value}
            <span className="ml-1 text-xs font-normal text-text-3">
              {c.suffix}
            </span>
          </div>
          {c.delta !== undefined && (
            <div
              className={`mt-1 text-xs ${c.delta >= 0 ? "text-success" : "text-danger"}`}
            >
              {c.delta >= 0 ? (
                <TrendingUp className="mr-0.5 inline h-3 w-3" />
              ) : (
                <TrendingDown className="mr-0.5 inline h-3 w-3" />
              )}
              {Math.abs(c.delta)} 较昨/上周
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function RunningTasks() {
  const tasksMap = useTasks((s) => s.tasks);
  const liveTasks = useMemo(
    () =>
      Object.values(tasksMap)
        .filter((t: PipelineTask) =>
          ["running", "pending", "waiting_confirm"].includes(t.status),
        )
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
        .slice(0, 4),
    [tasksMap],
  );
  const { data } = useQuery({
    queryKey: ["tasks", "running"],
    queryFn: async () => {
      const [running, waiting, pending] = await Promise.all([
        pipelineApi.list("running", 1, 4),
        pipelineApi.list("waiting_confirm", 1, 4),
        pipelineApi.list("pending", 1, 4),
      ]);
      return [...running.items, ...waiting.items, ...pending.items].slice(0, 4);
    },
  });
  const list = liveTasks.length > 0 ? liveTasks : (data ?? []);

  return (
    <div className="glass p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-medium">进行中任务</span>
        <Link to="/tasks" className="text-xs text-brand-to hover:underline">
          全部任务 →
        </Link>
      </div>
      {list.length === 0 ? (
        <div className="py-6 text-center text-sm text-text-3">
          暂无进行中任务，
          <Link to="/create" className="text-brand-to hover:underline">
            立即创建 →
          </Link>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {list.map((t) => (
            <TaskCard key={t.id} task={t} compact />
          ))}
        </div>
      )}
    </div>
  );
}

function FeedPanel() {
  const { data } = useQuery({
    queryKey: ["feed"],
    queryFn: () => dashboardApi.feed(),
  });
  return (
    <div className="glass p-4">
      <div className="mb-3 font-medium">任务动态</div>
      <div className="space-y-2.5">
        {(data ?? []).slice(0, 10).map((ev) => (
          <FeedItem key={ev.id + ev.createdAt} ev={ev} />
        ))}
        {(data ?? []).length === 0 && (
          <div className="py-4 text-center text-xs text-text-3">暂无动态</div>
        )}
      </div>
    </div>
  );
}

function FeedItem({
  ev,
}: {
  ev: { id: string; type: string; text: string; createdAt: string };
}) {
  const rel = useRelativeTime(ev.createdAt);
  const color =
    ev.type === "ok"
      ? "bg-success"
      : ev.type === "err"
        ? "bg-danger"
        : ev.type === "run"
          ? "bg-info"
          : "bg-brand-from";
  return (
    <div className="flex items-start gap-2.5 text-sm">
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${color}`} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-text-2">{ev.text}</div>
        <div className="text-[11px] text-text-3">{rel}</div>
      </div>
    </div>
  );
}

function IpPanel() {
  const { current } = useIp();
  if (!current) return null;
  return (
    <div className="glass p-4">
      <div className="mb-3 text-xs text-text-3">当前 IP</div>
      <div className="flex items-center gap-3">
        <span
          className="flex h-12 w-12 items-center justify-center rounded-2xl text-xl font-bold text-white"
          style={{ background: current.avatarGrad }}
        >
          {current.avatarChar}
        </span>
        <div>
          <div className="font-bold">{current.name}</div>
          <div className="text-xs text-text-3">{current.domain}</div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="chip">{current.tone || "未设口吻"}</span>
        {current.tabooWords.slice(0, 2).map((w) => (
          <span key={w} className="chip border-danger/30 text-danger/80">
            禁:{w}
          </span>
        ))}
      </div>
      <Link to="/assets/personas" className="btn-ghost mt-3 w-full text-xs">
        管理 IP 档案
      </Link>
    </div>
  );
}

function QuickLinks() {
  const links: { to: string; icon: LucideIcon; label: string }[] = [
    { to: "/create", icon: Zap, label: "一键成片" },
    { to: "/scripts", icon: PenLine, label: "文案工坊" },
    { to: "/assets/voices", icon: Music, label: "克隆声音" },
    { to: "/publish/accounts", icon: Send, label: "授权账号" },
  ];
  return (
    <div className="glass p-4">
      <div className="mb-3 font-medium">快捷入口</div>
      <div className="grid grid-cols-2 gap-2">
        {links.map((l) => (
          <Link
            key={l.to}
            to={l.to}
            className="card-hover flex flex-col items-center gap-1.5 rounded-xl border border-stroke bg-white/[0.03] py-3 text-sm"
          >
            <span className="text-text-2">
              <l.icon className="h-5 w-5" />
            </span>
            <span className="text-xs text-text-2">{l.label}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

/** 工作台（对齐效果图 index.html：Hero + 数据卡 + 任务 + IP + 动态流 + 快捷入口） */
export default function DashboardPage() {
  return (
    <div className="space-y-5">
      <HeroInput />
      <StatCards />
      <div className="grid gap-5 xl:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          <RunningTasks />
        </div>
        <div className="space-y-5">
          <IpPanel />
          <FeedPanel />
          <QuickLinks />
        </div>
      </div>
      <div className="hidden">
        {/* STEP_LABELS 引用防止 tree-shake 提示（步骤标签供 mini-pipe 使用） */}
        {Object.values(STEP_LABELS).join(",")}
      </div>
    </div>
  );
}
