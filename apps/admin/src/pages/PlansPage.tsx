import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import type { ReactNode } from "react";
import { adminApi, type PlanSku } from "../lib/adminHttp";

const emptyPlan = {
  code: "",
  name: "",
  subtitle: "",
  description: "",
  badge: "",
  sortOrder: 0,
  skuType: "annual_bundle",
  audience: "public",
  durationDays: 365,
  monthlyPoints: 1000,
  oneTimePoints: 0,
  listPriceCents: 199900,
  displayPriceCents: 169900,
  entitlements: "digital_human,voice_clone,1080p_export",
  maxConcurrency: 2,
  maxResolution: "1080p",
  purchaseInstructions: "联系管理员获取激活码",
};

export default function PlansPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(emptyPlan);
  const [message, setMessage] = useState("");
  const [effectiveAt, setEffectiveAt] = useState("");
  const {
    data = [],
    isLoading,
    error,
  } = useQuery({ queryKey: ["admin-plans"], queryFn: adminApi.listPlans });

  const create = useMutation({
    mutationFn: () =>
      adminApi.createPlan({
        ...form,
        skuType: form.skuType as PlanSku["skuType"],
        audience: form.audience as PlanSku["audience"],
        entitlements: form.entitlements
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      }),
    onSuccess: async () => {
      setMessage("SKU 草稿已创建");
      setForm(emptyPlan);
      await queryClient.invalidateQueries({ queryKey: ["admin-plans"] });
    },
  });

  const publish = useMutation({
    mutationFn: (id: string) =>
      adminApi.publishPlan(
        id,
        effectiveAt ? new Date(effectiveAt).toISOString() : undefined,
      ),
    onSuccess: async () => {
      setMessage("SKU 已发布");
      await queryClient.invalidateQueries({ queryKey: ["admin-plans"] });
    },
  });

  const clone = useMutation({
    mutationFn: adminApi.clonePlan,
    onSuccess: async () => {
      setMessage("已克隆为新草稿版本");
      await queryClient.invalidateQueries({ queryKey: ["admin-plans"] });
    },
  });

  const retire = useMutation({
    mutationFn: adminApi.retirePlan,
    onSuccess: async () => {
      setMessage("SKU 已下架，已激活用户权益不变");
      await queryClient.invalidateQueries({ queryKey: ["admin-plans"] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    create.mutate();
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[420px_1fr]">
      <form className="glass h-fit space-y-4 p-5" onSubmit={submit}>
        <div>
          <h1 className="text-xl font-semibold">新建套餐 SKU</h1>
          <p className="mt-1 text-sm text-text-3">
            经济字段发布后不可直接修改，后续通过克隆版本迭代。
          </p>
        </div>
        <TextField
          label="SKU 编码"
          value={form.code}
          onChange={(code) => setForm({ ...form, code })}
        />
        <TextField
          label="用户端名称"
          value={form.name}
          onChange={(name) => setForm({ ...form, name })}
        />
        <TextField
          label="副标题"
          value={form.subtitle}
          onChange={(subtitle) => setForm({ ...form, subtitle })}
        />
        <TextField
          label="角标"
          value={form.badge}
          onChange={(badge) => setForm({ ...form, badge })}
        />
        <label className="block">
          <span className="label">套餐说明</span>
          <textarea
            className="input min-h-24"
            value={form.description}
            onChange={(event) =>
              setForm({ ...form, description: event.target.value })
            }
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <SelectField
            label="类型"
            value={form.skuType}
            onChange={(skuType) => setForm({ ...form, skuType })}
          >
            <option value="trial">trial</option>
            <option value="annual_bundle">annual_bundle</option>
            <option value="internal_annual">internal_annual</option>
            <option value="points_pack">points_pack</option>
          </SelectField>
          <SelectField
            label="范围"
            value={form.audience}
            onChange={(audience) => setForm({ ...form, audience })}
          >
            <option value="public">public</option>
            <option value="internal">internal</option>
          </SelectField>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField
            label="服务天数"
            value={form.durationDays}
            onChange={(durationDays) => setForm({ ...form, durationDays })}
          />
          <NumberField
            label="展示排序"
            value={form.sortOrder}
            onChange={(sortOrder) => setForm({ ...form, sortOrder })}
          />
          <NumberField
            label="每月积分"
            value={form.monthlyPoints}
            onChange={(monthlyPoints) => setForm({ ...form, monthlyPoints })}
          />
          <NumberField
            label="一次性积分"
            value={form.oneTimePoints}
            onChange={(oneTimePoints) => setForm({ ...form, oneTimePoints })}
          />
          <NumberField
            label="原价（分）"
            value={form.listPriceCents}
            onChange={(listPriceCents) => setForm({ ...form, listPriceCents })}
          />
          <NumberField
            label="展示价（分）"
            value={form.displayPriceCents}
            onChange={(displayPriceCents) =>
              setForm({ ...form, displayPriceCents })
            }
          />
          <NumberField
            label="最大并发任务"
            value={form.maxConcurrency}
            onChange={(maxConcurrency) => setForm({ ...form, maxConcurrency })}
          />
        </div>
        <TextField
          label="最高导出清晰度"
          value={form.maxResolution}
          onChange={(maxResolution) => setForm({ ...form, maxResolution })}
        />
        <TextField
          label="权益编码（逗号分隔）"
          value={form.entitlements}
          onChange={(entitlements) => setForm({ ...form, entitlements })}
        />
        <TextField
          label="购买说明 / 联系方式"
          value={form.purchaseInstructions}
          onChange={(purchaseInstructions) =>
            setForm({ ...form, purchaseInstructions })
          }
        />
        <div className="rounded-2xl border border-stroke bg-white/[0.03] p-4 text-sm">
          <div className="flex items-center gap-2">
            <strong>{form.name || "套餐名称预览"}</strong>
            {form.badge && <span className="chip">{form.badge}</span>}
          </div>
          <p className="mt-2 text-text-3">
            ¥{(form.displayPriceCents / 100).toFixed(2)} / {form.durationDays}{" "}
            天 · 每月 {form.monthlyPoints} 积分 · {form.maxConcurrency} 并发 ·
            {form.maxResolution}
          </p>
        </div>
        <button
          className="btn-primary w-full"
          disabled={create.isPending || !form.code || !form.name}
        >
          创建草稿
        </button>
        {(message || create.error) && (
          <p className="text-sm text-text-2">
            {create.error instanceof Error ? create.error.message : message}
          </p>
        )}
      </form>

      <section className="glass p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold">SKU 列表</h2>
          {isLoading && <span className="text-sm text-text-3">加载中...</span>}
        </div>
        <label className="mb-4 block max-w-sm">
          <span className="label">定时生效（留空立即发布）</span>
          <input
            className="input"
            type="datetime-local"
            value={effectiveAt}
            onChange={(event) => setEffectiveAt(event.target.value)}
          />
        </label>
        {error instanceof Error && (
          <p className="mb-4 text-sm text-danger">{error.message}</p>
        )}
        <div className="space-y-3">
          {data.map((plan) => (
            <article
              key={plan.id}
              className="rounded-2xl border border-stroke bg-white/[0.03] p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold">{plan.name}</h3>
                    <span className="chip">{plan.code}</span>
                    <span className="chip">{plan.status}</span>
                    <span className="chip">v{plan.version}</span>
                  </div>
                  <p className="mt-2 text-sm text-text-3">
                    {plan.skuType} · {plan.audience} · {plan.durationDays} 天 ·
                    每月 {plan.monthlyPoints} 积分
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    className="btn-ghost"
                    disabled={plan.status !== "draft" || publish.isPending}
                    onClick={() => publish.mutate(plan.id)}
                  >
                    {effectiveAt ? "定时发布" : "发布"}
                  </button>
                  <button
                    className="btn-ghost"
                    disabled={clone.isPending}
                    onClick={() => clone.mutate(plan.id)}
                  >
                    克隆
                  </button>
                  <button
                    className="btn-ghost"
                    disabled={plan.status !== "published" || retire.isPending}
                    onClick={() => retire.mutate(plan.id)}
                  >
                    下架
                  </button>
                </div>
              </div>
            </article>
          ))}
          {data.length === 0 && !isLoading && (
            <p className="text-sm text-text-3">暂无套餐 SKU。</p>
          )}
        </div>
      </section>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <input
        className="input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <input
        className="input"
        type="number"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <select
        className="input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
    </label>
  );
}
