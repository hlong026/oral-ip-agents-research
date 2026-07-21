import { HttpError, pipelineApi } from "@oral/api-client";
import { useTasks } from "@oral/stores";
import { STEP_LABELS, type PipelineTask, type StepState } from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

const STEP_STATUS_ICON: Record<string, { icon: string; cls: string }> = {
  pending: { icon: "○", cls: "text-text-3" },
  running: { icon: "◉", cls: "animate-pulse text-info" },
  done: { icon: "●", cls: "text-success" },
  skipped: { icon: "—", cls: "text-text-3" },
  failed: { icon: "✕", cls: "text-danger" },
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
      <span className={`z-10 mt-0.5 w-6 text-center text-lg ${meta.cls}`}>
        {meta.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{STEP_LABELS[step.step]}</span>
          <span className="chip text-[11px]">{step.status}</span>
          {step.provider && (
            <span className="chip text-[11px]">{step.provider}</span>
          )}
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

/** 任务详情：8 步流水线时间线（F-405）+ manual 确认 + 成片预览 */
export default function TaskDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const liveTask = useTasks((s) => s.tasks[id]);
  const { data: fetched, refetch } = useQuery({
    queryKey: ["task", id],
    queryFn: () => pipelineApi.get(id),
    refetchInterval: (q) =>
      q.state.data?.status === "running" || q.state.data?.status === "pending"
        ? 3000
        : false,
  });
  const task = liveTask ?? fetched;

  if (!task)
    return <div className="py-16 text-center text-text-3">加载中…</div>;

  const refresh = () => {
    void refetch();
    void queryClient.invalidateQueries({ queryKey: ["task", id] });
  };

  const finalVideo = task.steps.find((s) => s.step === "compose")?.artifacts
    ?.final_video_key;
  const script = task.steps.find((s) => s.step === "rewrite")?.artifacts
    ?.script;

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
          <span className="text-warning">✋</span>
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
          <span className="text-danger">✕</span>
          <span className="flex-1 text-sm text-danger">
            任务失败：{task.error || "可从失败步骤重新报价后续跑"}
          </span>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_300px]">
        {/* 流水线时间线 */}
        <div className="glass p-5">
          <div className="mb-4 flex items-center justify-between">
            <span className="font-medium">流水线时间线</span>
            {(task.status === "running" ||
              task.status === "waiting_confirm") && (
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

        {/* 产物栏 */}
        <div className="space-y-4">
          {task.status === "done" && finalVideo && (
            <div className="glass p-4">
              <div className="mb-2 text-xs font-medium text-text-3">成片</div>
              <div className="rounded-xl border border-stroke bg-black/40 p-3 text-center text-xs text-text-3">
                <div className="mb-2 text-3xl">🎬</div>
                <div className="break-all">{finalVideo}</div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Link to="/editor" className="btn-ghost text-xs">
                  去剪辑精修
                </Link>
                <Link to="/publish/jobs" className="btn-primary text-xs">
                  去发布
                </Link>
              </div>
            </div>
          )}
          {script && (
            <div className="glass p-4">
              <div className="mb-2 text-xs font-medium text-text-3">
                口播文案
              </div>
              <div className="max-h-64 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-text-2">
                {script}
              </div>
            </div>
          )}
          <div className="glass p-4 text-xs text-text-3">
            <div>任务 ID：{task.id}</div>
            <div className="mt-1">
              创建：{new Date(task.createdAt).toLocaleString("zh-CN")}
            </div>
            <div className="mt-1">
              更新：{new Date(task.updatedAt).toLocaleString("zh-CN")}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
