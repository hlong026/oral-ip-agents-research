import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import { adminApi } from "../lib/adminHttp";

const REQUEST_SOURCE_LABEL: Record<string, string> = {
  "desktop-hw": "桌面端（硬件码）",
  web: "网页端",
};

function DeviceRequestsPanel() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<
    "pending" | "approved" | "rejected" | "all"
  >("pending");
  // 每个申请行已选择的待解绑旧设备 id
  const [unbindChoice, setUnbindChoice] = useState<Record<string, string>>({});
  const { data, isLoading, error } = useQuery({
    queryKey: ["device-requests", statusFilter],
    queryFn: () => adminApi.listDeviceRequests(statusFilter, 1, 50),
  });
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["device-requests"] });
    await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
  };
  const approve = useMutation({
    mutationFn: ({ id, unbindId }: { id: string; unbindId?: string }) =>
      adminApi.approveDeviceRequest(id, unbindId),
    onSuccess: refresh,
  });
  const reject = useMutation({
    mutationFn: (id: string) => adminApi.rejectDeviceRequest(id),
    onSuccess: refresh,
  });
  const limit = data?.limit ?? 1;

  return (
    <section className="glass p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">设备绑定审批</h2>
          <p className="mt-1 text-sm text-text-3">
            用户超出设备上限（当前 {limit}台）后自动提交申请；批准时选择要解绑的旧设备，新设备下次登录自动绑定。
          </p>
        </div>
        <select
          className="input w-36"
          value={statusFilter}
          onChange={(event) =>
            setStatusFilter(
              event.target.value as typeof statusFilter,
            )
          }
        >
          <option value="pending">待审批</option>
          <option value="approved">已批准</option>
          <option value="rejected">已拒绝</option>
          <option value="all">全部</option>
        </select>
      </div>
      {isLoading && <p className="mt-4 text-sm text-text-3">加载中...</p>}
      {error instanceof Error && (
        <p className="mt-4 text-sm text-danger">{error.message}</p>
      )}
      {(approve.error instanceof Error || reject.error instanceof Error) && (
        <p className="mt-4 text-sm text-danger">
          {(approve.error as Error)?.message ||
            (reject.error as Error)?.message}
        </p>
      )}
      <div className="mt-4 space-y-4">
        {(data?.items ?? []).map((item) => (
          <div
            key={item.id}
            className="rounded-lg border border-stroke/60 p-4"
          >
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">{item.nickname || "未知用户"}</span>
              <span className="font-mono text-xs text-text-3">
                {item.activationCodeMasked || "无激活码"}
              </span>
              <span className="chip">
                申请设备：{item.deviceName || item.deviceKey.slice(0, 12)}
              </span>
              <span className="text-xs text-text-3">
                {new Date(item.createdAt).toLocaleString()}
              </span>
              <span className="ml-auto text-xs">
                {item.status === "pending"
                  ? "待审批"
                  : item.status === "approved"
                    ? "已批准"
                    : "已拒绝"}
              </span>
            </div>
            {item.status === "pending" && (
              <div className="mt-3 space-y-2">
                <div className="text-xs text-text-3">
                  当前已绑设备（选择一台解绑以腾出名额）：
                </div>
                {item.boundDevices.map((device) => (
                  <label
                    key={device.id}
                    className="flex items-center gap-2 text-sm"
                  >
                    <input
                      type="radio"
                      name={`unbind-${item.id}`}
                      checked={unbindChoice[item.id] === device.id}
                      onChange={() =>
                        setUnbindChoice({
                          ...unbindChoice,
                          [item.id]: device.id,
                        })
                      }
                    />
                    <span>
                      {device.deviceName || "未命名设备"}
                      <span className="ml-2 text-xs text-text-3">
                        {REQUEST_SOURCE_LABEL[device.source] ?? device.source}
                        ，最近活跃{" "}
                        {new Date(device.lastSeenAt).toLocaleString()}
                      </span>
                    </span>
                  </label>
                ))}
                {item.boundDevices.length === 0 && (
                  <p className="text-xs text-text-3">
                    该用户当前无绑定设备，可直接批准。
                  </p>
                )}
                <div className="flex gap-2 pt-1">
                  <button
                    className="btn-primary"
                    disabled={
                      approve.isPending ||
                      (item.boundDevices.length >= limit &&
                        !unbindChoice[item.id])
                    }
                    onClick={() =>
                      approve.mutate({
                        id: item.id,
                        unbindId: unbindChoice[item.id],
                      })
                    }
                  >
                    {unbindChoice[item.id]
                      ? "批准并解绑所选"
                      : "批准"}
                  </button>
                  <button
                    className="btn-ghost"
                    disabled={reject.isPending}
                    onClick={() => reject.mutate(item.id)}
                  >
                    拒绝
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
        {!isLoading && (data?.items ?? []).length === 0 && (
          <p className="text-sm text-text-3">暂无申请</p>
        )}
      </div>
    </section>
  );
}

export default function ActivationPage() {
  const [tab, setTab] = useState<"codes" | "devices">("codes");
  const [name, setName] = useState("");
  const [skuVersionId, setSkuVersionId] = useState("");
  const [count, setCount] = useState(10);
  const [channel, setChannel] = useState("partner");
  const { data: plans = [], error } = useQuery({
    queryKey: ["admin-plans"],
    queryFn: adminApi.listPlans,
  });
  const publishedPlans = useMemo(
    () => plans.filter((plan) => plan.status === "published"),
    [plans],
  );

  const generate = useMutation({
    mutationFn: () =>
      adminApi.generateActivationBatch({ name, skuVersionId, count, channel }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    generate.mutate();
  }

  function downloadCodes() {
    if (!generate.data) return;
    const csv = ["activation_code", ...generate.data.codes]
      .map((value) => `"${value.replaceAll('"', '""')}"`)
      .join("\n");
    const url = URL.createObjectURL(
      new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `activation-${generate.data.batchId}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-5">
      <div className="flex gap-2">
        <button
          className={tab === "codes" ? "btn-primary" : "btn-ghost"}
          onClick={() => setTab("codes")}
        >
          激活码批次
        </button>
        <button
          className={tab === "devices" ? "btn-primary" : "btn-ghost"}
          onClick={() => setTab("devices")}
        >
          设备审批
        </button>
      </div>
      {tab === "devices" ? (
        <DeviceRequestsPanel />
      ) : (
        <div className="grid gap-5 xl:grid-cols-[420px_1fr]">
      <form className="glass h-fit space-y-4 p-5" onSubmit={submit}>
        <div>
          <h1 className="text-xl font-semibold">生成激活码批次</h1>
          <p className="mt-1 text-sm text-text-3">
            批次只能绑定已发布 SKU 版本，生成码只在本页返回一次。
          </p>
        </div>
        {error instanceof Error && (
          <p className="text-sm text-danger">{error.message}</p>
        )}
        <label className="block">
          <span className="label">批次名称</span>
          <input
            className="input"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="block">
          <span className="label">SKU 版本</span>
          <select
            className="input"
            value={skuVersionId}
            onChange={(event) => setSkuVersionId(event.target.value)}
          >
            <option value="">请选择已发布 SKU</option>
            {publishedPlans.map((plan) => (
              <option key={plan.id} value={plan.id}>
                {plan.name} · {plan.code} · v{plan.version}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label">渠道</span>
          <input
            className="input"
            value={channel}
            onChange={(event) => setChannel(event.target.value)}
          />
        </label>
        <label className="block">
          <span className="label">生成数量</span>
          <input
            className="input"
            type="number"
            min={1}
            max={1000}
            value={count}
            onChange={(event) => setCount(Number(event.target.value))}
          />
        </label>
        <button
          className="btn-primary w-full"
          disabled={!name || !skuVersionId || generate.isPending}
        >
          生成并导出
        </button>
        {generate.error instanceof Error && (
          <p className="text-sm text-danger">{generate.error.message}</p>
        )}
      </form>

      <section className="glass p-5">
        <h2 className="text-xl font-semibold">一次性激活码</h2>
        <p className="mt-1 text-sm text-text-3">
          明文码为五组五位字符（如 KTNPV-98W6R-8Q3M2-Y47CG-PDKV3）；CSV 仅在生成后提供一次，请立即保存。
        </p>
        {generate.data ? (
          <div className="mt-4">
            <div className="mb-3 flex flex-wrap gap-2 text-sm text-text-2">
              <span className="chip">批次 {generate.data.batchId}</span>
              <span className="chip">生成 {generate.data.generated} 个</span>
            </div>
            <textarea
              className="input h-80 font-mono text-xs"
              readOnly
              value={generate.data.codes.join("\n")}
              onFocus={(event) => event.currentTarget.select()}
            />
            <button
              type="button"
              className="btn-primary mt-3"
              onClick={downloadCodes}
            >
              下载一次性 CSV
            </button>
          </div>
        ) : (
          <p className="mt-4 text-sm text-text-3">
            生成后将在这里显示本批次明文码。
          </p>
        )}
      </section>
        </div>
      )}
    </div>
  );
}
