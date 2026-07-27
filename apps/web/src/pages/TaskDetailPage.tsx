import { HttpError, pipelineApi } from "@oral/api-client";
import { useTasks } from "@oral/stores";
import { STEP_LABELS, type PipelineTask, type StepState } from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Circle,
  CircleCheck,
  Clapperboard,
  Hand,
  LoaderCircle,
  type LucideIcon,
  Minus,
  X,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

const STEP_STATUS_ICON: Record<string, { icon: LucideIcon; cls: string }> = {
  pending: { icon: Circle, cls: "text-text-3" },
  running: { icon: LoaderCircle, cls: "animate-spin text-info" },
  done: { icon: CircleCheck, cls: "text-success" },
  skipped: { icon: Minus, cls: "text-text-3" },
  failed: { icon: X, cls: "text-danger" },
};

/** 单步时间线节点（重跑/人工覆盖入口） */
function StepNode({
  task,
  step,
  isLast,
  onAction,
}: {
  task: PipelineTask;
  step: StepState;
  isLast: boolean;
  onAction: () => void;
}) {
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideKey, setOverrideKey] = useState("");
  const [overrideVal, setOverrideVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [retryQuote, setRetryQuote] = useState<{
    quoteId: string;
    estimatedPoints: number;
    availablePoints: number;
  } | null>(null);
  const [actionError, setActionError] = useState("");
  const meta = STEP_STATUS_ICON[step.status] ?? STEP_STATUS_ICON.pending!;
  const canRetry =
    task.status !== "done" &&
    task.status !== "canceled" &&
    task.status !== "running" &&
    (step.status === "failed" || step.status === "done");
  const canOverride =
    step.status !== "running" &&
    task.status !== "running" &&
    task.status !== "done";

  const retry = async () => {
    setBusy(true);
    setActionError("");
    try {
      await pipelineApi.retryStep(task.id, step.step, retryQuote?.quoteId);
      setRetryQuote(null);
      onAction();
    } catch (error) {
      if (
        error instanceof HttpError &&
        error.body.code === "RETRY_REQUIRES_NEW_QUOTE"
      ) {
        try {
          const quote = await pipelineApi.retryQuote(task.id);
          setRetryQuote(quote);
        } catch (quoteError) {
          setActionError(
            quoteError instanceof HttpError
              ? quoteError.body.message
              : "重试报价获取失败",
          );
        }
      } else {
        setActionError(
          error instanceof HttpError ? error.body.message : "步骤重跑失败",
        );
      }
    } finally {
      setBusy(false);
    }
  };

  const override = async () => {
    if (!overrideKey.trim()) return;
    setBusy(true);
    try {
      await pipelineApi.overrideStep(task.id, step.step, {
        [overrideKey.trim()]: overrideVal,
      });
      setOverrideOpen(false);
      onAction();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex gap-4 pb-6">
      {!isLast && (
        <span className="absolute left-[11px] top-7 h-full w-px bg-stroke" />
      )}
      <span
        className={`z-10 mt-0.5 flex w-6 justify-center pt-0.5 ${meta.cls}`}
      >
        <meta.icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{STEP_LABELS[step.step]}</span>
          <span className="chip text-[11px]">{step.status}</span>
          {(step.quotaCost ?? 0) > 0 && (
            <span className="chip text-[11px]">{step.quotaCost} 点</span>
          )}
          {step.durationMs != null && (
            <span className="chip text-[11px]">
              {(step.durationMs / 1000).toFixed(1)} 秒
            </span>
          )}
          <div className="flex-1" />
          {canRetry && (
            <button
              onClick={retry}
              disabled={busy}
              className="btn-ghost px-2.5 py-0.5 text-xs"
            >
              重跑此步
            </button>
          )}
          {canOverride && (
            <button
              onClick={() => setOverrideOpen((v) => !v)}
              disabled={busy}
              className="btn-ghost px-2.5 py-0.5 text-xs"
            >
              人工覆盖
            </button>
          )}
        </div>
        {step.status === "running" && (
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full animate-pulse rounded-full bg-brand-grad-x"
              style={{ width: `${step.progress}%` }}
            />
          </div>
        )}
        {step.message && (
          <div
            className={`mt-1.5 text-xs ${step.status === "failed" ? "text-danger" : "text-text-3"}`}
          >
            {step.message}
          </div>
        )}
        {actionError && (
          <div className="mt-2 text-xs text-danger">{actionError}</div>
        )}
        {retryQuote && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs">
            <span className="flex-1 text-warning">
              本次续跑需重新冻结 {retryQuote.estimatedPoints} 点，当前可用{" "}
              {retryQuote.availablePoints} 点
            </span>
            <button
              className="btn-primary px-3 py-1 text-xs"
              disabled={busy}
              onClick={retry}
            >
              确认报价并续跑
            </button>
            <button
              className="btn-ghost px-3 py-1 text-xs"
              onClick={() => setRetryQuote(null)}
            >
              取消
            </button>
          </div>
        )}
        {step.artifacts && Object.keys(step.artifacts).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Object.entries(step.artifacts).map(([k, v]) =>
              v ? (
                <span
                  key={k}
                  className="chip max-w-64 truncate text-[11px]"
                  title={v}
                >
                  {k}: {v.length > 40 ? `${v.slice(0, 40)}…` : v}
                </span>
              ) : null,
            )}
          </div>
        )}
        {overrideOpen && (
          <div className="glass-strong mt-3 flex flex-wrap items-center gap-2 p-3">
            <input
              className="input h-8 w-40 text-xs"
              placeholder="产物键（如 script）"
              value={overrideKey}
              onChange={(e) => setOverrideKey(e.target.value)}
            />
            <input
              className="input h-8 flex-1 text-xs"
              placeholder="产物值（文本或 /media 链接）"
              value={overrideVal}
              onChange={(e) => setOverrideVal(e.target.value)}
            />
            <button
              onClick={override}
              disabled={busy || !overrideKey.trim()}
              className="btn-primary px-3 py-1 text-xs"
            >
              覆盖并续跑
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/** 任务详情：成片预览为主 + 进度条弱化展示（F-405，步骤详情可展开重跑/覆盖） */
export default function TaskDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const liveTask = useTasks((s) => s.tasks[id]);
  const {
    data: fetched,
    refetch,
    error: fetchError,
  } = useQuery({
    queryKey: ["task", id],
    queryFn: () => pipelineApi.get(id),
    refetchInterval: (q) => {
      // 404 等客户端错误属永久失败（任务不存在/已删除），停止轮询
      if (q.state.error instanceof HttpError && q.state.error.status < 500)
        return false;
      // 首拉失败时也持续重试，避免 WS 不可用时页面永久停在加载态
      if (!q.state.data) return 3000;
      const s = q.state.data.status;
      return s === "pending" || s === "running" || s === "waiting_confirm"
        ? 3000
        : false;
    },
    // 标签页切后台时也保持轮询，切回即见最新进度
    refetchIntervalInBackground: true,
  });
  const task = liveTask ?? fetched;
  // 4xx 为永久失败（任务不存在/已删除）；5xx 瞬时错误继续保持加载 + 轮询
  const notFound =
    !task && fetchError instanceof HttpError && fetchError.status < 500;

  if (notFound)
    return (
      <div className="py-16 text-center text-text-3">
        任务不存在或已删除，
        <Link className="text-brand-to underline" to="/tasks">
          返回任务中心
        </Link>
      </div>
    );
  if (!task)
    return <div className="py-16 text-center text-text-3">加载中…</div>;

  const refresh = () => {
    void refetch();
    void queryClient.invalidateQueries({ queryKey: ["task", id] });
  };

  // 任务级 artifacts 为全量产物；步骤级 artifacts 服务端截断至 200 字，仅供展示归因
  const art = (key: string) => {
    const v = task.artifacts?.[key];
    return typeof v === "string" && v ? v : undefined;
  };
  const composeStep = task.steps.find((s) => s.step === "compose");
  const finalVideo =
    art("final_video_key") ?? composeStep?.artifacts?.final_video_key;
  const coverKey = art("cover_key") ?? composeStep?.artifacts?.cover_key;
  const script =
    art("script") ??
    task.steps.find((s) => s.step === "rewrite")?.artifacts?.script;

  // 总体进度：skipped 不计入分母，运行中步骤按自身百分比折算
  const activeSteps = task.steps.filter((s) => s.status !== "skipped");
  const doneCount = activeSteps.filter((s) => s.status === "done").length;
  const runningStep = task.steps.find((s) => s.status === "running");
  const overallPct =
    task.status === "done"
      ? 100
      : Math.min(
          99,
          Math.round(
            ((doneCount + (runningStep ? runningStep.progress / 100 : 0)) /
              Math.max(activeSteps.length, 1)) *
              100,
          ),
        );
  const isFinished =
    task.status === "done" ||
    task.status === "failed" ||
    task.status === "canceled";

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => navigate(-1)}
          className="btn-ghost px-3 py-1.5 text-sm"
        >
          ← 返回
        </button>
        <h1 className="min-w-0 flex-1 truncate text-xl font-bold">
          {task.title}
        </h1>
        <span className="chip">
          {task.mode === "manual" ? "逐步确认" : "全自动"}
        </span>
        <span className="chip">消耗 {task.quotaCost.toFixed(0)} 点</span>
        {task.batchId && (
          <span className="chip border-brand-to/40 text-brand-to">
            批量 {task.batchId.slice(0, 6)}
          </span>
        )}
      </div>

      {/* manual 模式确认条 */}
      {task.status === "waiting_confirm" && (
        <div className="glass-strong flex items-center gap-3 border-warning/40 p-4">
          <span className="text-warning">
            <Hand className="h-4 w-4" />
          </span>
          <span className="flex-1 text-sm">
            当前步骤已完成，检查产物后确认继续（或直接重跑/覆盖）
          </span>
          <button
            className="btn-primary px-5"
            onClick={async () => {
              await pipelineApi.confirm(task.id);
              refresh();
            }}
          >
            确认，继续下一步 →
          </button>
        </div>
      )}

      {task.status === "failed" && (
        <div className="glass flex items-center gap-3 border-danger/40 p-4">
          <span className="text-danger">
            <X className="h-4 w-4" />
          </span>
          <span className="flex-1 text-sm text-danger">
            任务失败：{task.error || "可从失败步骤重新报价后续跑"}
          </span>
        </div>
      )}

      {/* 成片预览（主体）：就绪即内嵌播放，未就绪时以进度占位 */}
      <div className="glass p-5">
        <div className="mb-3 flex items-center justify-between">
          <span className="font-medium">成片预览</span>
          {finalVideo && (
            <div className="flex gap-2">
              <Link to="/editor" className="btn-ghost px-3 py-1.5 text-xs">
                去剪辑精修
              </Link>
              <Link
                to="/publish/jobs"
                className="btn-primary px-3 py-1.5 text-xs"
              >
                去发布
              </Link>
            </div>
          )}
        </div>
        {finalVideo ? (
          <video
            src={`/media/${finalVideo}`}
            poster={coverKey ? `/media/${coverKey}` : undefined}
            controls
            playsInline
            preload="metadata"
            className="max-h-[480px] w-full rounded-xl bg-black"
            aria-label="成片预览"
          />
        ) : (
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-xl border border-stroke bg-black/40 text-text-3">
            {isFinished ? (
              <>
                <Clapperboard className="h-9 w-9 text-text-2" />
                <span className="text-sm">
                  {task.status === "failed"
                    ? "合成未完成，可展开下方步骤详情从失败步续跑"
                    : "任务已取消，未生成成片"}
                </span>
              </>
            ) : (
              <>
                <LoaderCircle className="h-9 w-9 animate-spin text-info" />
                <span className="text-sm">
                  成片生成中…{" "}
                  {runningStep
                    ? `当前：${STEP_LABELS[runningStep.step]}`
                    : task.status === "waiting_confirm"
                      ? "等待人工确认"
                      : "等待调度"}
                </span>
                <span className="text-2xl font-bold text-text-1">
                  {overallPct}%
                </span>
              </>
            )}
          </div>
        )}
      </div>

      {/* 生成进度（弱化）：总进度条 + 步骤节点，详情按需展开 */}
      <div className="glass p-5">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">生成进度</span>
          <span className="text-xs text-text-3">
            {task.status === "done"
              ? "已完成"
              : runningStep
                ? `${STEP_LABELS[runningStep.step]}中…`
                : task.status === "failed"
                  ? "已失败"
                  : task.status === "canceled"
                    ? "已取消"
                    : task.status === "waiting_confirm"
                      ? "等待人工确认"
                      : "等待中"}
          </span>
          <div className="flex-1" />
          <span className="text-xs font-medium text-text-2">{overallPct}%</span>
          {(task.status === "running" || task.status === "waiting_confirm") && (
            <button
              className="btn-danger px-3 py-1 text-xs"
              onClick={async () => {
                await pipelineApi.cancel(task.id);
                refresh();
              }}
            >
              取消任务
            </button>
          )}
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/5">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              task.status === "failed" ? "bg-danger/70" : "bg-brand-grad-x"
            }`}
            style={{ width: `${overallPct}%` }}
          />
        </div>
        {/* 步骤节点一览（skipped 置灰） */}
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
          {task.steps.map((s) => {
            const m = STEP_STATUS_ICON[s.status] ?? STEP_STATUS_ICON.pending!;
            return (
              <span
                key={s.step}
                className={`flex items-center gap-1 text-xs ${
                  s.status === "skipped" || s.status === "pending"
                    ? "text-text-3/60"
                    : "text-text-2"
                }`}
              >
                <m.icon className={`h-3 w-3 ${m.cls}`} />
                {STEP_LABELS[s.step]}
              </span>
            );
          })}
        </div>
        <button
          className="mt-3 flex items-center gap-1 text-xs text-text-3 transition-colors hover:text-text-1"
          onClick={() => setDetailsOpen((v) => !v)}
        >
          <ChevronDown
            className={`h-3.5 w-3.5 transition-transform ${detailsOpen ? "rotate-180" : ""}`}
          />
          {detailsOpen ? "收起步骤详情" : "展开步骤详情（重跑 / 人工覆盖）"}
        </button>
        {detailsOpen && (
          <div className="mt-4 border-t border-stroke pt-4">
            {task.steps.map((s, i) => (
              <StepNode
                key={s.step}
                task={task}
                step={s}
                isLast={i === task.steps.length - 1}
                onAction={refresh}
              />
            ))}
          </div>
        )}
      </div>

      {/* 口播文案：全量展示不截断 */}
      {script && (
        <div className="glass p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className="font-medium">口播文案</span>
            <span className="text-xs text-text-3">{script.length} 字</span>
          </div>
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-text-2">
            {script}
          </div>
        </div>
      )}

      <div className="glass flex flex-wrap gap-x-6 gap-y-1 p-4 text-xs text-text-3">
        <span>任务 ID：{task.id}</span>
        <span>创建：{new Date(task.createdAt).toLocaleString("zh-CN")}</span>
        <span>更新：{new Date(task.updatedAt).toLocaleString("zh-CN")}</span>
      </div>
    </div>
  );
}
