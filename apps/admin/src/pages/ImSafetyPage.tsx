import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "../lib/adminHttp";

export default function ImSafetyPage() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["im-kill-switch"],
    queryFn: () => adminApi.imKillSwitch(),
  });
  const update = useMutation({
    mutationFn: (stopped: boolean) => adminApi.setImKillSwitch(stopped),
    onSuccess: (result) => {
      queryClient.setQueryData(["im-kill-switch"], result);
    },
  });

  const stopped = data?.stopped ?? true;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">私信自动回复安全</h1>
        <p className="mt-2 text-sm text-text-3">
          全局开关优先于用户授权；急停会立即取消所有尚未发送的自动回复任务。
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
                  : "已开放：仅已签署风险协议的账号可自动发送"}
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
    </div>
  );
}
