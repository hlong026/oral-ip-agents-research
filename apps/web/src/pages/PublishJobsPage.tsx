import { HttpError, publishApi } from "@oral/api-client";
import {
  PLATFORM_NAMES,
  PUBLISH_PLATFORMS,
  type PublishJob,
} from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import PlatformIcon from "../components/PlatformIcon";

const JOB_STATUS: Record<string, { label: string; cls: string }> = {
  queued: { label: "排队中", cls: "border-info/40 text-info" },
  publishing: { label: "发布中", cls: "border-warning/40 text-warning" },
  success: { label: "成功", cls: "border-success/40 text-success" },
  failed: { label: "失败", cls: "border-danger/40 text-danger" },
  export_ready: {
    label: "待人工发布",
    cls: "border-warning/40 text-warning",
  },
};

/** 单条发布任务行：状态追踪 / 失败原因 / 重试与完整人工发布包降级（F-504） */
function JobRow({ job, onAction }: { job: PublishJob; onAction: () => void }) {
  const [busy, setBusy] = useState(false);
  const [exported, setExported] = useState("");
  const meta = JOB_STATUS[job.status] ?? JOB_STATUS.queued!;

  const retry = async () => {
    setBusy(true);
    try {
      await publishApi.retryJob(job.id);
      onAction();
    } finally {
      setBusy(false);
    }
  };

  const exportMp4 = async () => {
    setBusy(true);
    try {
      const res = await publishApi.exportJob(job.id);
      setExported(res.packageUrl);
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className="border-b border-stroke/50 last:border-0">
      <td className="max-w-64 py-2.5 pr-3">
        <div className="truncate font-medium" title={job.title}>
          {job.title}
        </div>
        <div className="text-xs text-text-3">
          任务 {job.taskId.slice(0, 8)} · 重试 {job.retryCount} 次
        </div>
      </td>
      <td className="py-2.5 pr-3">
        <span className="chip text-[11px]">
          <PlatformIcon platform={job.platform} size={14} /> {job.platformName}
        </span>
      </td>
      <td className="py-2.5 pr-3 text-xs text-text-2">{job.accountNickname}</td>
      <td className="py-2.5 pr-3 text-xs text-text-3">
        {job.scheduledAt
          ? `定时 ${new Date(job.scheduledAt).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}`
          : "立即"}
      </td>
      <td className="py-2.5 pr-3">
        <span className={`chip text-[11px] ${meta.cls}`}>{meta.label}</span>
        {(job.status === "failed" || job.status === "export_ready") &&
          job.error && (
            <div
              className={`mt-1 max-w-52 text-xs ${job.status === "failed" ? "text-danger" : "text-warning"}`}
              title={job.error}
            >
              {job.error}
            </div>
          )}
        {exported && (
          <div
            className="mt-1 max-w-52 truncate text-xs text-success"
            title={exported}
          >
            发布包已就绪
          </div>
        )}
      </td>
      <td className="py-2.5">
        <div className="flex gap-1.5">
          {job.status === "failed" && (
            <button
              className="btn-primary px-2.5 py-0.5 text-xs"
              disabled={busy}
              onClick={retry}
            >
              重试
            </button>
          )}
          {(job.status === "failed" || job.status === "export_ready") && (
            <button
              className="btn-ghost px-2.5 py-0.5 text-xs"
              disabled={busy}
              onClick={exportMp4}
            >
              生成发布包
            </button>
          )}
          {(exported || job.packageUrl) && (
            <a
              className="btn-ghost px-2.5 py-0.5 text-xs"
              href={exported || job.packageUrl || "#"}
              target="_blank"
              rel="noreferrer"
            >
              下载 ZIP
            </a>
          )}
          {job.status === "success" && job.videoUrl && (
            <a
              className="btn-ghost px-2.5 py-0.5 text-xs"
              href={job.videoUrl}
              target="_blank"
              rel="noreferrer"
            >
              查看
            </a>
          )}
        </div>
      </td>
    </tr>
  );
}

/** 发布管理（F-501~F-504）；/publish/logs 复用本页（showLogs 全量日志） */
export default function PublishJobsPage({
  showLogs = false,
}: {
  showLogs?: boolean;
}) {
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const taskFilter = params.get("task") ?? "";

  const { data: accounts } = useQuery({
    queryKey: ["publish-accounts"],
    queryFn: () => publishApi.accounts(),
  });
  const { data: capabilities } = useQuery({
    queryKey: ["publish-capabilities"],
    queryFn: () => publishApi.capabilities(),
  });
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["publish-jobs", showLogs ? "logs" : status, page],
    queryFn: () =>
      showLogs
        ? publishApi.logs(page, 50)
        : publishApi.jobs(status || undefined, page, 12),
    refetchInterval: 10_000,
  });

  const expired = (accounts ?? []).filter((a) => a.status === "expired");
  const items = (data?.items ?? []).filter(
    (j) => !taskFilter || j.taskId === taskFilter,
  );

  const refresh = () => {
    void refetch();
    void queryClient.invalidateQueries({ queryKey: ["publish-jobs"] });
  };

  const reauth = async (accountId: string) => {
    setError("");
    try {
      await publishApi.reauth(accountId);
      void queryClient.invalidateQueries({ queryKey: ["publish-accounts"] });
    } catch (e) {
      setError(e instanceof HttpError ? e.body.message : "发起授权失败");
    }
  };

  const FILTERS = [
    { key: "", label: "全部" },
    { key: "queued", label: "排队中" },
    { key: "publishing", label: "发布中" },
    { key: "success", label: "成功" },
    { key: "failed", label: "失败" },
    { key: "export_ready", label: "待人工发布" },
  ] as const;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">
            {showLogs ? "发布日志" : "发布管理"}
          </h1>
          <p className="mt-1 text-sm text-text-3">
            多平台分发 · 定时发布 · 未验收能力自动降级为完整人工发布包
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/publish/jobs"
            className={`chip px-3 py-1.5 ${!showLogs ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}
          >
            发布任务
          </Link>
          <Link
            to="/publish/logs"
            className={`chip px-3 py-1.5 ${showLogs ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}
          >
            全量日志
          </Link>
          <Link
            to="/publish/accounts"
            className="btn-ghost px-3 py-1.5 text-xs"
          >
            账号管理 →
          </Link>
        </div>
      </div>

      {/* 登录态失效告警（首屏最重要） */}
      {expired.length > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-card border border-danger/40 bg-danger/10 px-4 py-3">
          <span className="flex items-center gap-1.5 text-sm text-danger">
            <TriangleAlert className="h-4 w-4 shrink-0" />
            <span>
              {expired
                .map((a) => `${a.platformName}账号「${a.nickname}」`)
                .join("、")}
              登录态已过期，待发布任务被阻塞。
            </span>
          </span>
          <button
            className="btn-primary px-3 py-1 text-xs"
            onClick={() => void reauth(expired[0]!.id)}
          >
            一键重新授权
          </button>
        </div>
      )}
      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/10 px-4 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      {(capabilities ?? []).some((item) => !item.automaticEnabled) && (
        <div className="rounded-card border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
          未完成真实账号验收的平台只生成包含视频、封面和发布文案的 ZIP
          发布包，不会触发自动发布。
        </div>
      )}

      {/* 平台账号健康状态 */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {PUBLISH_PLATFORMS.map((p) => {
          const capability = (capabilities ?? []).find(
            (item) => item.platform === p,
          );
          const bound = (accounts ?? []).filter((a) => a.platform === p);
          const hasExpired = bound.some((a) => a.status === "expired");
          return (
            <div key={p} className="glass flex items-center gap-3 p-4">
              <PlatformIcon platform={p} size={28} />
              <div className="min-w-0 flex-1">
                <div className="font-medium">{PLATFORM_NAMES[p]}</div>
                <div
                  className={`text-xs ${hasExpired ? "text-danger" : "text-text-3"}`}
                >
                  {!capability?.automaticEnabled
                    ? "仅支持人工发布包"
                    : bound.length === 0
                      ? "未绑定账号"
                      : hasExpired
                        ? "登录态失效"
                        : `${bound.length} 个账号正常`}
                </div>
              </div>
              <span
                className={`chip text-[11px] ${
                  bound.length === 0
                    ? ""
                    : hasExpired
                      ? "border-danger/40 text-danger"
                      : "border-success/40 text-success"
                }`}
              >
                {!capability?.automaticEnabled
                  ? "未验收"
                  : bound.length === 0
                    ? "未绑定"
                    : hasExpired
                      ? "异常"
                      : "正常"}
              </span>
            </div>
          );
        })}
      </div>

      {/* 筛选（日志页不显示） */}
      {!showLogs && (
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
          {taskFilter && (
            <span className="chip border-brand-to/40 text-brand-to">
              仅看任务 {taskFilter.slice(0, 8)}
            </span>
          )}
        </div>
      )}

      {/* jobs 表格 */}
      <div className="glass p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">
            {showLogs ? "全量发布日志" : "发布任务"}（{data?.total ?? 0}）
          </h2>
          <span className="text-xs text-text-3">每 10s 自动刷新</span>
        </div>
        {isLoading && (
          <div className="py-12 text-center text-text-3">加载中…</div>
        )}
        {!isLoading && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-stroke text-left text-xs text-text-3">
                  <th className="pb-2 pr-3 font-medium">视频</th>
                  <th className="pb-2 pr-3 font-medium">平台</th>
                  <th className="pb-2 pr-3 font-medium">账号</th>
                  <th className="pb-2 pr-3 font-medium">时间</th>
                  <th className="pb-2 pr-3 font-medium">状态</th>
                  <th className="pb-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((j) => (
                  <JobRow key={j.id} job={j} onAction={refresh} />
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-text-3">
                      暂无发布任务，成片完成后可在任务详情一键发布
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {(data?.total ?? 0) > (showLogs ? 50 : 12) && (
          <div className="mt-4 flex items-center justify-center gap-3 text-sm">
            <button
              className="btn-ghost px-3 py-1"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              上一页
            </button>
            <span className="text-text-3">
              {page} / {Math.ceil((data?.total ?? 0) / (showLogs ? 50 : 12))}
            </span>
            <button
              className="btn-ghost px-3 py-1"
              disabled={page * (showLogs ? 50 : 12) >= (data?.total ?? 0)}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
