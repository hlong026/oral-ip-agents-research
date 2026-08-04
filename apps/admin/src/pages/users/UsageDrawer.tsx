import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { adminApi } from "../../lib/adminHttp";

interface UserUsageDrawerProps {
  userId: string;
  userName: string;
  userPhone: string | null;
  activationCodeMasked: string | null;
  balance: number;
  onClose: () => void;
}

const STEP_LABEL: Record<string, string> = {
  parse: "视频解析",
  asr: "语音识别",
  rewrite: "文案改写",
  script_generation: "脚本生成",
  voice: "语音合成",
  tts: "TTS 合成",
  avatar: "数字人训练",
  digital_human: "数字人驱动",
  compose: "视频合成",
  hd_export: "高清导出",
};

export default function UserUsageDrawer({
  userId,
  userName,
  userPhone,
  activationCodeMasked,
  balance,
  onClose,
}: UserUsageDrawerProps) {
  const [page, setPage] = useState(1);
  const [stepFilter, setStepFilter] = useState("");

  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["admin-user-usage", userId, page, stepFilter],
    queryFn: () =>
      adminApi.getUserUsage(userId, page, 20, stepFilter || undefined),
  });

  const exportCsv = useMutation({
    mutationFn: (step?: string) => adminApi.downloadUserUsageCsv(userId, step),
    onSuccess: (blob) => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const safeName = userName.replace(/[\/\\:*?"<>|]/g, "_");
      a.download = `usage_${safeName}_${new Date().toISOString().split("T")[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    },
  });

  const formatDateTime = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  };

  const handleStepChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setStepFilter(e.target.value);
    setPage(1);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40"
      onClick={onClose}
    >
      <aside
        className="glass h-full w-full max-w-md space-y-5 overflow-y-auto p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">{userName} 的详情</h2>
            <p className="text-xs text-text-3">基本信息与调用记录</p>
          </div>
          <button className="btn-ghost" onClick={onClose}>
            关闭
          </button>
        </div>

        {/* 基本信息卡片 */}
        <div className="rounded-lg border border-stroke/60 bg-surface-1 p-4 space-y-3">
          <h3 className="text-sm font-semibold text-text-2">基本信息</h3>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-text-3">用户名:</span>{" "}
              <span className="font-medium">{userName}</span>
            </div>
            <div>
              <span className="text-text-3">手机号:</span>{" "}
              <span className="font-medium">{userPhone || "未绑定"}</span>
            </div>
            <div>
              <span className="text-text-3">激活码:</span>{" "}
              <span className="font-mono font-medium">
                {activationCodeMasked || "未激活"}
              </span>
            </div>
            <div>
              <span className="text-text-3">余额:</span>{" "}
              <span className="font-mono font-medium text-success">
                {balance.toLocaleString()} 点
              </span>
            </div>
          </div>
        </div>

        {/* 筛选器 */}
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-text-3">步骤筛选:</span>
            <select
              className="input"
              value={stepFilter}
              onChange={handleStepChange}
              disabled={isFetching}
            >
              <option value="">全部步骤</option>
              {Object.entries(STEP_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button
            className="btn-ghost text-sm"
            onClick={() => exportCsv.mutate(stepFilter || undefined)}
            disabled={exportCsv.isPending || isLoading}
          >
            {exportCsv.isPending ? "导出中..." : "导出 CSV"}
          </button>
        </div>

        {/* 错误提示 */}
        {error instanceof Error && (
          <div className="rounded-lg border border-danger/50 bg-danger/10 p-3 text-sm text-danger">
            {error.message}
          </div>
        )}

        {/* 调用记录表格 */}
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-text-2">调用记录</h3>
          {isLoading && (
            <div className="flex items-center justify-center p-8 text-text-3">
              加载中...
            </div>
          )}
          {!isLoading && !error && (
            <>
              <div className="overflow-hidden rounded-lg border border-stroke/60">
                <table className="w-full text-sm">
                  <thead className="border-b border-stroke text-left text-text-3">
                    <tr>
                      <th className="px-3 py-2">时间</th>
                      <th className="px-3 py-2">步骤</th>
                      <th className="px-3 py-2 text-right">积分</th>
                      <th className="px-3 py-2 text-right">通道</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.items ?? []).map((item) => (
                      <tr
                        key={item.id}
                        className="border-b border-stroke/50 last:border-0"
                      >
                        <td className="px-3 py-2 font-mono text-xs text-text-3">
                          {formatDateTime(item.createdAt)}
                        </td>
                        <td className="px-3 py-2">
                          <span className="rounded bg-surface-2 px-2 py-0.5 text-xs font-medium">
                            {STEP_LABEL[item.step] || item.step}
                          </span>
                        </td>
                        <td
                          className={`px-3 py-2 text-right font-mono ${item.points < 0 ? "text-success" : ""}`}
                        >
                          {item.points > 0
                            ? `-${item.points}`
                            : item.points === 0
                              ? "0"
                              : `+${-item.points}（退还）`}
                        </td>
                        <td className="px-3 py-2 text-right text-text-3">
                          {item.compute}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* 分页 */}
              <div className="flex items-center justify-between text-sm text-text-3">
                <span>
                  共 {data?.total ?? 0} 条记录，第 {page} 页
                </span>
                <div className="flex gap-2">
                  <button
                    className="btn-ghost text-sm"
                    onClick={() => setPage(Math.max(1, page - 1))}
                    disabled={page === 1 || isFetching}
                  >
                    上一页
                  </button>
                  <button
                    className="btn-ghost text-sm"
                    onClick={() => setPage(page + 1)}
                    disabled={!data?.hasMore || isFetching}
                  >
                    下一页
                  </button>
                </div>
              </div>
            </>
          )}
          {!isLoading && !error && (data?.items ?? []).length === 0 && (
            <div className="flex items-center justify-center p-8 text-text-3">
              暂无调用记录
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
