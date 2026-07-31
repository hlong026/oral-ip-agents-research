import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  type AdminRetryPreflight,
  type AdminTask,
  type AdminTaskFilters,
  adminApi,
} from "../lib/adminHttp";

const failureLabels: Record<AdminTask["failureClass"], string> = {
  none: "无",
  network: "网络异常",
  authentication: "认证失败",
  platform_verification: "平台验证",
  content: "内容问题",
  account: "账号失效",
  internal: "内部错误",
};

type TaskAction = { kind: "retry" | "cancel"; task: AdminTask } | null;

function formatFailureClasses(classes: Record<string, number> | undefined) {
  if (!classes) return "暂无失败";
  const entries = Object.entries(classes).filter(([, count]) => count > 0);
  if (entries.length === 0) return "暂无失败";
  return entries
    .map(([kind, count]) => {
      const label = failureLabels[kind as AdminTask["failureClass"]] ?? kind;
      return `${label} ${count}`;
    })
    .join(" · ");
}

export default function TasksPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<AdminTaskFilters>({});
  const [appliedFilters, setAppliedFilters] = useState<AdminTaskFilters>({});
  const [action, setAction] = useState<TaskAction>(null);
  const [reason, setReason] = useState("");
  const [retryStep, setRetryStep] = useState("");
  const [retryPreflight, setRetryPreflight] =
    useState<AdminRetryPreflight | null>(null);
  const [preflightError, setPreflightError] = useState("");
  const [preflightLoading, setPreflightLoading] = useState(false);
  const tasks = useQuery({
    queryKey: ["admin-tasks", appliedFilters],
    queryFn: () => adminApi.listTasks(appliedFilters),
  });
  const health = useQuery({
    queryKey: ["operations-health", 24],
    queryFn: () => adminApi.operationsHealth(24),
    refetchInterval: 60_000,
  });
  const operate = useMutation({
    mutationFn: async () => {
      if (!action) throw new Error("未选择任务");
      if (action.kind === "retry") {
        return adminApi.retryTask(
          action.task.id,
          retryStep,
          reason,
          retryPreflight?.quote?.quoteId,
        );
      }
      return adminApi.cancelTask(action.task.id, reason);
    },
    onSuccess: async () => {
      setAction(null);
      setReason("");
      setRetryPreflight(null);
      setPreflightError("");
      await queryClient.invalidateQueries({ queryKey: ["admin-tasks"] });
    },
  });

  const chooseAction = async (kind: "retry" | "cancel", task: AdminTask) => {
    setAction({ kind, task });
    setRetryStep(task.step);
    setReason("");
    setRetryPreflight(null);
    setPreflightError("");
    if (kind !== "retry") return;
    setPreflightLoading(true);
    try {
      setRetryPreflight(await adminApi.retryTaskQuote(task.id));
    } catch (error) {
      setPreflightError(
        error instanceof Error ? error.message : "重试计费检查失败",
      );
    } finally {
      setPreflightLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">全局任务运维</h1>
        <p className="mt-2 text-sm text-text-3">
          跨用户定位生产任务；重试和取消沿用业务状态机并写入审计，不直接修改终态。
        </p>
      </div>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <HealthCard
          label="发布成功率"
          value={`${health.data?.publishing.successRate ?? 0}%`}
          detail={`失败 ${health.data?.publishing.failed ?? 0} · 恢复 ${health.data?.publishing.recovered ?? 0}`}
        />
        <HealthCard
          label="人工兜底率"
          value={`${health.data?.publishing.manualFallbackRate ?? 0}%`}
          detail={`发布包 ${health.data?.publishing.manualFallback ?? 0}`}
        />
        <HealthCard
          label="Provider 失败"
          value={String(
            health.data?.providers.reduce(
              (total, item) => total + item.failures,
              0,
            ) ?? 0,
          )}
          detail={`配额告警 ${
            health.data?.providers.reduce(
              (total, item) => total + item.quotaFailures,
              0,
            ) ?? 0
          }`}
          danger={Boolean(
            health.data?.providers.some((item) => item.quotaAlert),
          )}
        />
        <HealthCard
          label="发布失败分类"
          value={String(health.data?.publishing.failed ?? 0)}
          detail={formatFailureClasses(health.data?.publishing.failureClasses)}
          danger={Boolean(health.data?.publishing.failed)}
        />
        <HealthCard
          label="待人工对账"
          value={String(health.data?.billing.unknownOutcomes ?? 0)}
          detail={`冻结 ${health.data?.billing.reserved ?? 0} · 释放 ${health.data?.billing.released ?? 0}`}
          danger={Boolean(health.data?.billing.unknownOutcomes)}
        />
      </section>

      <section className="glass p-5">
        <form
          className="grid gap-3 md:grid-cols-2 xl:grid-cols-5"
          onSubmit={(event) => {
            event.preventDefault();
            setAppliedFilters(filters);
          }}
        >
          <input
            className="input"
            placeholder="用户 ID"
            value={filters.userId ?? ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                userId: event.target.value.trim(),
              }))
            }
          />
          <select
            className="input"
            value={filters.status ?? ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                status: event.target.value,
              }))
            }
          >
            <option value="">全部状态</option>
            <option value="pending">待执行</option>
            <option value="running">执行中</option>
            <option value="failed">失败</option>
            <option value="reconciliation_required">待对账</option>
            <option value="done">完成</option>
            <option value="canceled">已取消</option>
          </select>
          <input
            className="input"
            placeholder="步骤，例如 voice"
            value={filters.step ?? ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                step: event.target.value.trim(),
              }))
            }
          />
          <input
            className="input"
            placeholder="Provider"
            value={filters.provider ?? ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                provider: event.target.value.trim(),
              }))
            }
          />
          <button className="btn-primary" type="submit">
            查询任务
          </button>
        </form>
      </section>

      <section className="glass overflow-hidden">
        <div className="border-b border-white/10 px-5 py-4 text-sm text-text-3">
          共 {tasks.data?.total ?? 0} 条
        </div>
        <div className="divide-y divide-white/10">
          {tasks.data?.items.map((task) => (
            <article
              key={task.id}
              className="grid gap-4 px-5 py-4 xl:grid-cols-[1.4fr_1fr_1fr_auto]"
            >
              <div>
                <p className="font-medium">{task.title}</p>
                <p className="mt-1 text-xs text-text-3">
                  {task.userNickname || "未知用户"} · {task.userId}
                </p>
                <p className="mt-1 font-mono text-[11px] text-text-3">
                  {task.id}
                </p>
              </div>
              <div className="text-sm">
                <p>
                  {task.status} · {task.step || "未开始"}
                </p>
                <p className="mt-1 text-xs text-text-3">
                  {task.provider || "内部"} · {failureLabels[task.failureClass]}
                </p>
                {task.errorSummary ? (
                  <p className="mt-1 text-xs text-danger">
                    {task.errorSummary}
                  </p>
                ) : null}
              </div>
              <div className="text-xs text-text-3">
                <p>追踪号</p>
                <p className="mt-1 font-mono text-text-2">{task.traceId}</p>
                <p className="mt-2">
                  更新于 {new Date(task.updatedAt).toLocaleString("zh-CN")}
                </p>
              </div>
              <div className="flex items-start gap-2">
                {task.status === "failed" ? (
                  <button
                    className="btn-primary whitespace-nowrap px-3 py-1.5 text-xs"
                    onClick={() => void chooseAction("retry", task)}
                  >
                    受控重试
                  </button>
                ) : null}
                {["pending", "running", "waiting_confirm"].includes(
                  task.status,
                ) ? (
                  <button
                    className="rounded-lg border border-danger/40 px-3 py-1.5 text-xs text-danger hover:bg-danger/10"
                    onClick={() => void chooseAction("cancel", task)}
                  >
                    受控取消
                  </button>
                ) : null}
              </div>
            </article>
          ))}
          {!tasks.isLoading && tasks.data?.items.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-text-3">
              当前筛选条件下没有任务。
            </p>
          ) : null}
        </div>
      </section>

      {action ? (
        <section className="glass max-w-2xl border border-warning/30 p-5">
          <h2 className="font-medium">
            {action.kind === "retry" ? "确认受控重试" : "确认受控取消"}
          </h2>
          <p className="mt-2 text-sm text-text-3">
            {action.task.title} · {action.task.id}
          </p>
          {action.kind === "retry" ? (
            <>
              <input
                className="input mt-4"
                aria-label="重试步骤"
                value={retryStep}
                onChange={(event) => setRetryStep(event.target.value.trim())}
              />
              <p className="mt-3 text-xs text-text-3">
                {preflightLoading
                  ? "正在检查原积分冻结…"
                  : retryPreflight?.required
                    ? `本次重试需重新冻结 ${retryPreflight.quote?.estimatedPoints ?? 0} 点，用户当前可用 ${retryPreflight.quote?.availablePoints ?? 0} 点`
                    : retryPreflight
                      ? "沿用原积分冻结，不重复扣费"
                      : "尚未完成积分检查"}
              </p>
              {preflightError ? (
                <p className="mt-2 text-xs text-danger">{preflightError}</p>
              ) : null}
            </>
          ) : null}
          <textarea
            className="input mt-3 min-h-24"
            aria-label="操作原因"
            placeholder="填写可审计的操作原因（至少 3 个字）"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="mt-3 flex gap-2">
            <button
              className="btn-primary"
              disabled={
                reason.trim().length < 3 ||
                (action.kind === "retry" && !retryStep) ||
                (action.kind === "retry" && !retryPreflight) ||
                (retryPreflight?.required && !retryPreflight.quote) ||
                Boolean(preflightError) ||
                preflightLoading ||
                operate.isPending
              }
              onClick={() => operate.mutate()}
            >
              确认执行
            </button>
            <button
              className="btn-ghost"
              disabled={operate.isPending}
              onClick={() => {
                setAction(null);
                setRetryPreflight(null);
                setPreflightError("");
              }}
            >
              取消
            </button>
          </div>
        </section>
      ) : null}

      {[tasks.error, health.error, operate.error]
        .filter((error): error is Error => error instanceof Error)
        .map((error) => (
          <p key={error.message} className="text-sm text-danger">
            {error.message}
          </p>
        ))}
    </div>
  );
}

function HealthCard({
  label,
  value,
  detail,
  danger = false,
}: {
  label: string;
  value: string;
  detail: string;
  danger?: boolean;
}) {
  return (
    <div className="glass p-4">
      <p className="text-xs text-text-3">{label}</p>
      <p
        className={`mt-2 text-2xl font-semibold ${danger ? "text-danger" : "text-text-1"}`}
      >
        {value}
      </p>
      <p className="mt-1 text-xs text-text-3">{detail}</p>
    </div>
  );
}
