import { useMutation, useQuery } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import { adminApi } from "../lib/adminHttp";

export default function ActivationPage() {
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
          后端不应在列表接口再次返回完整明文码，请立即复制保存。
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
  );
}
