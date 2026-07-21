import {
  STEP_LABELS,
  STEP_ORDER,
  type PipelineTask,
  type StepStatus,
} from "@oral/types";
import { Link } from "react-router-dom";

const STATUS_TEXT: Record<string, { label: string; cls: string }> = {
  pending: { label: "排队中", cls: "text-text-3 border-stroke" },
  running: { label: "执行中", cls: "text-info border-info/40" },
  waiting_confirm: { label: "待确认", cls: "text-warning border-warning/40" },
  done: { label: "已完成", cls: "text-success border-success/40" },
  failed: { label: "失败", cls: "text-danger border-danger/40" },
  canceled: { label: "已取消", cls: "text-text-3 border-stroke" },
};

function stepDot(status: StepStatus | undefined) {
  switch (status) {
    case "done":
      return "bg-success";
    case "running":
      return "animate-pulse bg-info";
    case "failed":
      return "bg-danger";
    case "skipped":
      return "bg-text-3/50";
    default:
      return "bg-white/10";
  }
}

/** 任务卡（工作台 mini-pipe 与任务中心共用 PipelineTask 统一模型） */
export default function TaskCard({
  task,
  compact = false,
}: {
  task: PipelineTask;
  compact?: boolean;
}) {
  const st = STATUS_TEXT[task.status] ?? STATUS_TEXT.pending!;
  const currentStep = task.steps.find((s) => s.status === "running");
  const doneCount = task.steps.filter(
    (s) => s.status === "done" || s.status === "skipped",
  ).length;
  const pct = Math.round((doneCount / STEP_ORDER.length) * 100);

  return (
    <Link
      to={`/tasks/${task.id}`}
      className="card-hover block rounded-xl border border-stroke bg-white/[0.03] p-3.5"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {task.title}
        </span>
        <span className={`chip shrink-0 ${st.cls}`}>{st.label}</span>
      </div>

      {/* mini-pipe：8 步状态点 */}
      <div className="mt-2.5 flex items-center gap-1">
        {STEP_ORDER.map((step) => {
          const s = task.steps.find((x) => x.step === step);
          return (
            <span
              key={step}
              title={`${STEP_LABELS[step]}：${s?.status ?? "pending"}`}
              className={`h-1.5 flex-1 rounded-full ${stepDot(s?.status)}`}
            />
          );
        })}
      </div>

      <div className="mt-2 flex items-center justify-between text-[11px] text-text-3">
        <span>
          {task.status === "running" && currentStep
            ? `${STEP_LABELS[currentStep.step]} 中…`
            : task.status === "waiting_confirm"
              ? `${task.currentStep ? (STEP_LABELS[task.currentStep as keyof typeof STEP_LABELS] ?? "") : ""} 完成，等待确认`
              : `${doneCount}/${STEP_ORDER.length} 步`}
        </span>
        <span>
          {task.mode === "manual" ? "手动" : "自动"} · {pct}% ·{" "}
          {task.quotaCost.toFixed(0)} 点
        </span>
      </div>

      {!compact && task.coverUrl && (
        <div className="mt-2 overflow-hidden rounded-lg border border-stroke">
          <img
            src={task.coverUrl}
            alt=""
            className="h-28 w-full object-cover"
          />
        </div>
      )}
    </Link>
  );
}
