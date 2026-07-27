import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { adminApi } from "@oral/admin-api-client";

export default function ImSafetyPage() {
  const queryClient = useQueryClient();
  const [accountId, setAccountId] = useState("");
  const [incidentAccountId, setIncidentAccountId] = useState("");
  const [incidentDetail, setIncidentDetail] = useState("");
  const { data, isLoading } = useQuery({
    queryKey: ["im-kill-switch"],
    queryFn: () => adminApi.imKillSwitch(),
  });
  const gray = useQuery({
    queryKey: ["im-gray-accounts"],
    queryFn: () => adminApi.listImGrayAccounts(),
  });
  const monitoring = useQuery({
    queryKey: ["im-monitoring", 24],
    queryFn: () => adminApi.imMonitoring(24),
    refetchInterval: 60_000,
  });
  const update = useMutation({
    mutationFn: (stopped: boolean) => adminApi.setImKillSwitch(stopped),
    onSuccess: (result) => {
      queryClient.setQueryData(["im-kill-switch"], result);
    },
  });
  const approve = useMutation({
    mutationFn: (id: string) => adminApi.approveImGrayAccount(id),
    onSuccess: async () => {
      setAccountId("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["im-gray-accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["im-monitoring"] }),
      ]);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => adminApi.removeImGrayAccount(id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["im-gray-accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["im-monitoring"] }),
      ]);
    },
  });
  const incident = useMutation({
    mutationFn: () =>
      adminApi.recordImRiskIncident(incidentAccountId, incidentDetail),
    onSuccess: async () => {
      setIncidentAccountId("");
      setIncidentDetail("");
      await queryClient.invalidateQueries({ queryKey: ["im-monitoring"] });
    },
  });

  const stopped = data?.stopped ?? true;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">私信自动回复安全</h1>
        <p className="mt-2 text-sm text-text-3">
          全局开关优先于灰度名单和用户授权；急停会立即取消所有尚未发送的自动回复任务。
        </p>
      </div>
      <section className="glass max-w-2xl p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="font-medium">全局 Kill Switch</h2>
            <p className="mt-2 text-sm text-text-3">
              {isLoading
                ? "正在读取当前状态…"
                : stopped
                  ? "已停止：所有账号均不能自动发送"
                  : "已开放：仅灰度名单内且已签署风险协议的账号可自动发送"}
            </p>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs ${
              stopped
                ? "bg-danger/15 text-danger"
                : "bg-success/15 text-success"
            }`}
          >
            {stopped ? "全局停止" : "受控开放"}
          </span>
        </div>
        <div className="mt-5 flex gap-2">
          <button
            className="rounded-lg border border-danger/40 px-4 py-2 text-sm text-danger hover:bg-danger/10"
            disabled={update.isPending || stopped}
            onClick={() => void update.mutateAsync(true)}
          >
            立即全局急停
          </button>
          <button
            className="btn-primary px-4 py-2 text-sm"
            disabled={update.isPending || !stopped}
            onClick={() => void update.mutateAsync(false)}
          >
            恢复受控自动回复
          </button>
        </div>
        {update.data?.canceledMessages ? (
          <p className="mt-3 text-xs text-warning">
            本次已取消 {update.data.canceledMessages} 条排队消息。
          </p>
        ) : null}
      </section>

      <section className="glass p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="font-medium">24 小时灰度监控</h2>
            <p className="mt-2 text-sm text-text-3">
              指标每分钟刷新；归属越权或风控事件出现时应立即全局急停。
            </p>
          </div>
          <span className="text-xs text-text-3">
            {monitoring.data
              ? `${monitoring.data.windowStart} — ${monitoring.data.windowEnd}`
              : "正在读取…"}
          </span>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="灰度账号" value={monitoring.data?.grayAccounts} />
          <Metric
            label="监听在线"
            value={`${monitoring.data?.listeningAccounts ?? 0}/${monitoring.data?.listenerAccounts ?? 0}`}
          />
          <Metric
            label="连接成功率"
            value={`${monitoring.data?.connectionSuccessRate ?? 0}%`}
          />
          <Metric
            label="连接掉线率"
            value={`${monitoring.data?.dropoutRate ?? 0}%`}
          />
          <Metric
            label="发送成功率"
            value={`${monitoring.data?.sendSuccessRate ?? 0}%`}
          />
          <Metric
            label="限额 / 审核拦截"
            value={`${monitoring.data?.quotaRejected ?? 0} / ${monitoring.data?.moderationBlocked ?? 0}`}
          />
          <Metric label="凭证失效" value={monitoring.data?.credentialExpired} />
          <Metric
            label="越权 / 风控事件"
            value={`${monitoring.data?.ownershipRejected ?? 0} / ${monitoring.data?.riskControlIncidents ?? 0}`}
            danger={
              Boolean(monitoring.data?.ownershipRejected) ||
              Boolean(monitoring.data?.riskControlIncidents)
            }
          />
        </div>
      </section>

      <section className="glass p-5">
        <h2 className="font-medium">灰度账号名单</h2>
        <div className="mt-4 flex max-w-2xl gap-2">
          <input
            className="input"
            placeholder="发布账号 ID"
            value={accountId}
            onChange={(event) => setAccountId(event.target.value.trim())}
          />
          <button
            className="btn-primary whitespace-nowrap"
            disabled={!accountId || approve.isPending}
            onClick={() => approve.mutate(accountId)}
          >
            加入灰度
          </button>
        </div>
        <div className="mt-4 space-y-2">
          {gray.data?.map((account) => (
            <div
              key={account.accountId}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/10 px-4 py-3"
            >
              <div>
                <p className="text-sm font-medium">
                  {account.nickname || account.accountId}
                </p>
                <p className="mt-1 text-xs text-text-3">
                  {account.accountId} · 操作人 {account.approvedBy}
                </p>
              </div>
              <button
                className="rounded-lg border border-danger/40 px-3 py-1.5 text-xs text-danger hover:bg-danger/10"
                disabled={remove.isPending}
                onClick={() => remove.mutate(account.accountId)}
              >
                移出并停用
              </button>
            </div>
          ))}
          {!gray.isLoading && gray.data?.length === 0 ? (
            <p className="text-sm text-text-3">尚未批准任何灰度账号。</p>
          ) : null}
        </div>
      </section>

      <section className="glass max-w-2xl p-5">
        <h2 className="font-medium">登记平台风控事件</h2>
        <p className="mt-2 text-sm text-text-3">
          记录后会进入七日灰度证据；账号 ID 可留空表示全局事件。
        </p>
        <div className="mt-4 space-y-3">
          <input
            className="input"
            placeholder="发布账号 ID（可选）"
            value={incidentAccountId}
            onChange={(event) =>
              setIncidentAccountId(event.target.value.trim())
            }
          />
          <textarea
            className="input min-h-24"
            placeholder="事件说明"
            value={incidentDetail}
            onChange={(event) => setIncidentDetail(event.target.value)}
          />
          <button
            className="rounded-lg border border-warning/40 px-4 py-2 text-sm text-warning hover:bg-warning/10"
            disabled={!incidentDetail.trim() || incident.isPending}
            onClick={() => incident.mutate()}
          >
            登记事件
          </button>
        </div>
      </section>

      {[
        gray.error,
        monitoring.error,
        approve.error,
        remove.error,
        incident.error,
      ]
        .filter((error): error is Error => error instanceof Error)
        .map((error, index) => (
          <p key={`${index}-${error.message}`} className="text-sm text-danger">
            {error.message}
          </p>
        ))}
    </div>
  );
}

function Metric({
  label,
  value,
  danger = false,
}: {
  label: string;
  value: string | number | undefined;
  danger?: boolean;
}) {
  return (
    <div className="rounded-lg border border-white/10 p-4">
      <p className="text-xs text-text-3">{label}</p>
      <p
        className={`mt-2 text-xl font-semibold ${danger ? "text-danger" : ""}`}
      >
        {value ?? 0}
      </p>
    </div>
  );
}
