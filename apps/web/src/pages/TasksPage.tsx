import { pipelineApi } from "@oral/api-client";
import { useTasks } from "@oral/stores";
import type { PipelineTask } from "@oral/types";
import { useQuery } from "@tanstack/react-query";
import { Zap } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import TaskCard from "../components/TaskCard";

const FILTERS = [
  { key: "", label: "全部" },
  { key: "running", label: "执行中" },
  { key: "waiting_confirm", label: "待确认" },
  { key: "reconciliation_required", label: "待对账" },
  { key: "done", label: "已完成" },
  { key: "failed", label: "失败" },
] as const;

/** 任务中心（F-405 流水线时间线入口；WS 实时进度接入任务卡） */
export default function TasksPage() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const q = params.get("q") ?? "";
  const tasksMap = useTasks((s) => s.tasks);

  const { data, isLoading } = useQuery({
    queryKey: ["tasks", status, page],
    queryFn: () => pipelineApi.list(status || undefined, page, 12),
    refetchInterval: 15_000, // WS 断线兜底轮询
    refetchIntervalInBackground: true, // 后台也保持，切回即见最新进度
  });

  // WS 推送的实时任务覆盖列表中的同 id 任务
  const items = useMemo(() => {
    let list: PipelineTask[] = (data?.items ?? []).map(
      (t) => tasksMap[t.id] ?? t,
    );
    if (q) list = list.filter((t) => t.title.includes(q));
    return list;
  }, [data, tasksMap, q]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">任务中心</h1>
          <p className="mt-1 text-sm text-text-3">
            8 步流水线实时进度 · 单步重跑 / 版本化精修 / 批量队列
          </p>
        </div>
        <Link to="/create" className="btn-primary flex items-center gap-1.5">
          <Zap className="h-4 w-4" /> 一键成片
        </Link>
      </div>

      <div className="flex gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => {
              setStatus(f.key);
              setPage(1);
            }}
            className={`chip px-3 py-1 ${status === f.key ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}
          >
            {f.label}
          </button>
        ))}
        {q && (
          <span className="chip border-brand-to/40 text-brand-to">
            搜索：{q}
          </span>
        )}
      </div>

      {isLoading && (
        <div className="py-16 text-center text-text-3">加载中…</div>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((t) => (
          <TaskCard key={t.id} task={t} />
        ))}
      </div>

      {!isLoading && items.length === 0 && (
        <div className="glass py-16 text-center text-text-3">
          暂无任务，
          <Link to="/create" className="text-brand-to hover:underline">
            创建第一个成片任务 →
          </Link>
        </div>
      )}

      {(data?.total ?? 0) > 12 && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button
            className="btn-ghost px-3 py-1"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            上一页
          </button>
          <span className="text-text-3">
            {page} / {Math.ceil((data?.total ?? 0) / 12)}
          </span>
          <button
            className="btn-ghost px-3 py-1"
            disabled={page * 12 >= (data?.total ?? 0)}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}
