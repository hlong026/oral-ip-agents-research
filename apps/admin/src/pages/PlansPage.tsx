import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { adminApi, type PlanSku } from "../lib/adminHttp";

/** 套餐类型预设：选择类型后自动带出常用配置，运营无需理解英文枚举 */
const SKU_TYPE_PRESETS: Record<
  PlanSku["skuType"],
  {
    label: string;
    hint: string;
    durationDays: number;
    pointsMode: "monthly" | "oneTime";
  }
> = {
  trial: {
    label: "试用体验",
    hint: "短期体验，积分一次性发放",
    durationDays: 7,
    pointsMode: "oneTime",
  },
  weekly_bundle: {
    label: "周会员",
    hint: "7 天服务期，积分一次性发放",
    durationDays: 7,
    pointsMode: "oneTime",
  },
  monthly_bundle: {
    label: "月度会员",
    hint: "30 天服务期，积分一次性发放",
    durationDays: 30,
    pointsMode: "oneTime",
  },
  quarterly_bundle: {
    label: "季度会员",
    hint: "90 天服务期，积分按月发放",
    durationDays: 90,
    pointsMode: "monthly",
  },
  annual_bundle: {
    label: "年度会员",
    hint: "对外销售主力，积分按月发放",
    durationDays: 365,
    pointsMode: "monthly",
  },
  internal_annual: {
    label: "内部年度",
    hint: "内部团队使用，不对外展示",
    durationDays: 365,
    pointsMode: "monthly",
  },
  points_pack: {
    label: "积分加油包",
    hint: "补充积分，一次性到账",
    durationDays: 365,
    pointsMode: "oneTime",
  },
};

/** 权益勾选项：编码 → 用户可读名称 */
const ENTITLEMENT_OPTIONS: { code: string; label: string }[] = [
  { code: "digital_human", label: "数字人形象" },
  { code: "voice_clone", label: "声音克隆" },
  { code: "1080p_export", label: "1080p 高清导出" },
  { code: "4k_export", label: "4K 超清导出" },
  { code: "priority_queue", label: "任务优先处理" },
];

const RESOLUTION_OPTIONS = ["720p", "1080p", "4k"];

const STATUS_LABELS: Record<PlanSku["status"], string> = {
  draft: "草稿",
  scheduled: "待生效",
  published: "已发布",
  retired: "已下架",
};

const AUDIENCE_LABELS: Record<PlanSku["audience"], string> = {
  public: "公开销售",
  internal: "仅限内部",
};

interface PlanForm {
  code: string;
  name: string;
  subtitle: string;
  description: string;
  badge: string;
  sortOrder: number;
  skuType: PlanSku["skuType"];
  audience: PlanSku["audience"];
  durationDays: number;
  pointsMode: "monthly" | "oneTime";
  pointsAmount: number;
  listPriceYuan: string;
  displayPriceYuan: string;
  entitlements: string[];
  extraEntitlements: string;
  maxConcurrency: number;
  maxResolution: string;
  purchaseInstructions: string;
}

const emptyPlan: PlanForm = {
  code: "",
  name: "",
  subtitle: "",
  description: "",
  badge: "",
  sortOrder: 0,
  skuType: "annual_bundle",
  audience: "public",
  durationDays: 365,
  pointsMode: "monthly",
  pointsAmount: 1000,
  listPriceYuan: "1999",
  displayPriceYuan: "1699",
  entitlements: ["digital_human", "voice_clone", "1080p_export"],
  extraEntitlements: "",
  maxConcurrency: 2,
  maxResolution: "1080p",
  purchaseInstructions: "联系管理员获取激活码",
};

function yuanToCents(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
}

/** 自动生成套餐编码：类型-日期-随机后缀，运营无需手填 */
function genCode(skuType: PlanSku["skuType"]): string {
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const rand = Math.random().toString(36).slice(2, 5);
  return `${skuType.replace(/_/g, "-")}-${date}-${rand}`;
}

export default function PlansPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<PlanForm>(() => ({
    ...emptyPlan,
    code: genCode(emptyPlan.skuType),
  }));
  const [codeEdited, setCodeEdited] = useState(false);
  const [showOptionalCopy, setShowOptionalCopy] = useState(false);
  const [message, setMessage] = useState("");
  const [effectiveAt, setEffectiveAt] = useState("");
  const {
    data = [],
    isLoading,
    error,
  } = useQuery({ queryKey: ["admin-plans"], queryFn: adminApi.listPlans });

  const allEntitlements = useMemo(() => {
    const extra = form.extraEntitlements
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    return [...form.entitlements, ...extra];
  }, [form.entitlements, form.extraEntitlements]);

  const create = useMutation({
    mutationFn: () =>
      adminApi.createPlan({
        code: form.code,
        name: form.name,
        subtitle: form.subtitle,
        description: form.description,
        badge: form.badge,
        sortOrder: form.sortOrder,
        skuType: form.skuType,
        audience: form.audience,
        durationDays: form.durationDays,
        monthlyPoints: form.pointsMode === "monthly" ? form.pointsAmount : 0,
        oneTimePoints: form.pointsMode === "oneTime" ? form.pointsAmount : 0,
        listPriceCents: yuanToCents(form.listPriceYuan),
        displayPriceCents: yuanToCents(form.displayPriceYuan),
        entitlements: allEntitlements,
        maxConcurrency: form.maxConcurrency,
        maxResolution: form.maxResolution,
        purchaseInstructions: form.purchaseInstructions,
      }),
    onSuccess: async () => {
      setMessage("SKU 草稿已创建");
      setForm({ ...emptyPlan, code: genCode(emptyPlan.skuType) });
      setCodeEdited(false);
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

  function pickSkuType(skuType: PlanSku["skuType"]) {
    const preset = SKU_TYPE_PRESETS[skuType];
    setForm({
      ...form,
      skuType,
      durationDays: preset.durationDays,
      pointsMode: preset.pointsMode,
      audience: skuType === "internal_annual" ? "internal" : form.audience,
      // 编码未被手动改过时，跟随类型自动重新生成
      code: codeEdited ? form.code : genCode(skuType),
    });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    create.mutate();
  }

  const displayPrice = Number(form.displayPriceYuan) || 0;
  const listPrice = Number(form.listPriceYuan) || 0;

  return (
    <div className="grid gap-5 xl:grid-cols-[460px_1fr]">
      <form className="glass h-fit p-6" onSubmit={submit}>
        <h1 className="font-serif text-2xl font-semibold tracking-wide">
          新建套餐
        </h1>
        <p className="mt-1 text-sm text-text-3">
          价格与积分发布后锁定，后续通过「克隆」迭代新版本。
        </p>

        <SectionTitle>基本信息</SectionTitle>
        <div className="space-y-3">
          <TextField
            label="套餐名称（用户可见）"
            placeholder="如：旗舰年度会员"
            value={form.name}
            onChange={(name) => setForm({ ...form, name })}
          />
          <TextField
            label="套餐编码（已自动生成，一般无需修改）"
            value={form.code}
            onChange={(code) => {
              setCodeEdited(true);
              setForm({ ...form, code });
            }}
          />
          <button
            type="button"
            className="text-sm text-text-3 underline-offset-4 hover:text-text-2 hover:underline"
            onClick={() => setShowOptionalCopy((prev) => !prev)}
          >
            {showOptionalCopy
              ? "收起营销文案"
              : "营销文案：副标题 / 角标 / 说明（选填，不填则购买页不显示）"}
          </button>
          {showOptionalCopy && (
            <div className="space-y-3 border-t border-stroke pt-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField
                  label="副标题"
                  placeholder="一句话卖点"
                  value={form.subtitle}
                  onChange={(subtitle) => setForm({ ...form, subtitle })}
                />
                <TextField
                  label="促销角标"
                  placeholder="如：限时特惠"
                  value={form.badge}
                  onChange={(badge) => setForm({ ...form, badge })}
                />
              </div>
              <label className="block">
                <span className="label">套餐说明（展示在购买页）</span>
                <textarea
                  className="input min-h-20"
                  value={form.description}
                  onChange={(event) =>
                    setForm({ ...form, description: event.target.value })
                  }
                />
              </label>
            </div>
          )}
        </div>

        <SectionTitle>套餐类型</SectionTitle>
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            Object.entries(SKU_TYPE_PRESETS) as [
              PlanSku["skuType"],
              (typeof SKU_TYPE_PRESETS)[PlanSku["skuType"]],
            ][]
          ).map(([value, preset]) => (
            <button
              key={value}
              type="button"
              onClick={() => pickSkuType(value)}
              className={`rounded-xl border px-3 py-2.5 text-left transition ${
                form.skuType === value
                  ? "border-accent bg-accent/10"
                  : "border-stroke hover:border-text-3"
              }`}
            >
              <span className="block text-sm font-medium">{preset.label}</span>
              <span className="mt-0.5 block text-xs text-text-3">
                {preset.hint}
              </span>
            </button>
          ))}
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <NumberField
            label="服务期（天）"
            value={form.durationDays}
            onChange={(durationDays) => setForm({ ...form, durationDays })}
          />
          <SelectField
            label="售卖范围"
            value={form.audience}
            onChange={(audience) =>
              setForm({ ...form, audience: audience as PlanSku["audience"] })
            }
          >
            <option value="public">公开销售</option>
            <option value="internal">仅限内部</option>
          </SelectField>
        </div>

        <SectionTitle>积分发放</SectionTitle>
        <div className="flex gap-2">
          {(
            [
              ["monthly", "按月发放", "每月到账，防止一次性用完"],
              ["oneTime", "一次性发放", "激活后立即全部到账"],
            ] as const
          ).map(([mode, label, hint]) => (
            <button
              key={mode}
              type="button"
              onClick={() => setForm({ ...form, pointsMode: mode })}
              className={`flex-1 rounded-xl border px-3 py-2.5 text-left transition ${
                form.pointsMode === mode
                  ? "border-accent bg-accent/10"
                  : "border-stroke hover:border-text-3"
              }`}
            >
              <span className="block text-sm font-medium">{label}</span>
              <span className="mt-0.5 block text-xs text-text-3">{hint}</span>
            </button>
          ))}
        </div>
        <div className="mt-3">
          <NumberField
            label={
              form.pointsMode === "monthly" ? "每月发放积分" : "一次性发放积分"
            }
            value={form.pointsAmount}
            onChange={(pointsAmount) => setForm({ ...form, pointsAmount })}
          />
        </div>

        <SectionTitle>定价</SectionTitle>
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label="划线原价（元）"
            placeholder="如：1999"
            value={form.listPriceYuan}
            onChange={(listPriceYuan) => setForm({ ...form, listPriceYuan })}
          />
          <TextField
            label="实际售价（元）"
            placeholder="如：1699"
            value={form.displayPriceYuan}
            onChange={(displayPriceYuan) =>
              setForm({ ...form, displayPriceYuan })
            }
          />
        </div>
        {listPrice > 0 && displayPrice > 0 && listPrice < displayPrice && (
          <p className="mt-2 text-sm text-danger">
            实际售价高于划线原价，请确认是否填反。
          </p>
        )}

        <SectionTitle>用户权益</SectionTitle>
        <div className="space-y-2">
          {ENTITLEMENT_OPTIONS.map((option) => (
            <label
              key={option.code}
              className="flex cursor-pointer items-center gap-2.5 text-sm"
            >
              <input
                type="checkbox"
                className="h-4 w-4 accent-accent"
                checked={form.entitlements.includes(option.code)}
                onChange={(event) =>
                  setForm({
                    ...form,
                    entitlements: event.target.checked
                      ? [...form.entitlements, option.code]
                      : form.entitlements.filter(
                          (code) => code !== option.code,
                        ),
                  })
                }
              />
              {option.label}
              <span className="text-xs text-text-3">{option.code}</span>
            </label>
          ))}
          <TextField
            label="其他权益编码（选填，逗号分隔）"
            placeholder="如：custom_avatar"
            value={form.extraEntitlements}
            onChange={(extraEntitlements) =>
              setForm({ ...form, extraEntitlements })
            }
          />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <NumberField
            label="同时进行任务数上限"
            value={form.maxConcurrency}
            onChange={(maxConcurrency) => setForm({ ...form, maxConcurrency })}
          />
          <SelectField
            label="最高导出清晰度"
            value={form.maxResolution}
            onChange={(maxResolution) => setForm({ ...form, maxResolution })}
          >
            {RESOLUTION_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </SelectField>
        </div>

        <SectionTitle>购买引导</SectionTitle>
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label="购买说明 / 联系方式"
            value={form.purchaseInstructions}
            onChange={(purchaseInstructions) =>
              setForm({ ...form, purchaseInstructions })
            }
          />
          <NumberField
            label="展示排序（越小越靠前）"
            value={form.sortOrder}
            onChange={(sortOrder) => setForm({ ...form, sortOrder })}
          />
        </div>

        <div className="mt-6 rounded-2xl border border-stroke bg-white/[0.03] p-4">
          <p className="text-xs uppercase tracking-widest text-text-3">
            用户端预览
          </p>
          <div className="mt-2 flex items-center gap-2">
            <strong className="text-lg">{form.name || "套餐名称"}</strong>
            {form.badge && <span className="chip">{form.badge}</span>}
          </div>
          {form.subtitle && (
            <p className="mt-1 text-sm text-text-2">{form.subtitle}</p>
          )}
          <p className="mt-2 text-sm">
            <span className="text-xl font-semibold text-accent">
              ¥{displayPrice.toFixed(2)}
            </span>
            {listPrice > displayPrice && (
              <span className="ml-2 text-text-3 line-through">
                ¥{listPrice.toFixed(2)}
              </span>
            )}
            <span className="ml-2 text-text-3">/ {form.durationDays} 天</span>
          </p>
          <p className="mt-1 text-sm text-text-3">
            {form.pointsMode === "monthly"
              ? `每月 ${form.pointsAmount} 积分`
              : `一次性 ${form.pointsAmount} 积分`}
            {" · "}
            {form.maxConcurrency} 个并发任务 · 最高 {form.maxResolution}
          </p>
          {allEntitlements.length > 0 && (
            <p className="mt-1 text-sm text-text-3">
              含权益：
              {allEntitlements
                .map(
                  (code) =>
                    ENTITLEMENT_OPTIONS.find((item) => item.code === code)
                      ?.label ?? code,
                )
                .join("、")}
            </p>
          )}
        </div>

        <button
          className="btn-primary mt-4 w-full"
          disabled={create.isPending || !form.code || !form.name}
        >
          保存为草稿
        </button>
        {(message || create.error) && (
          <p className="mt-2 text-sm text-text-2">
            {create.error instanceof Error ? create.error.message : message}
          </p>
        )}
      </form>

      <section className="glass p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-serif text-2xl font-semibold tracking-wide">
            套餐列表
          </h2>
          {isLoading && <span className="text-sm text-text-3">加载中...</span>}
        </div>
        <label className="mb-4 block max-w-sm">
          <span className="label">定时生效时间（留空则立即发布）</span>
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
                    <span className="chip">
                      {STATUS_LABELS[plan.status] ?? plan.status}
                    </span>
                    <span className="chip">第 {plan.version} 版</span>
                  </div>
                  <p className="mt-2 text-sm text-text-3">
                    {SKU_TYPE_PRESETS[plan.skuType]?.label ?? plan.skuType}
                    {" · "}
                    {AUDIENCE_LABELS[plan.audience] ?? plan.audience}
                    {" · "}
                    {plan.durationDays} 天 · ¥
                    {(plan.displayPriceCents / 100).toFixed(2)}
                    {" · "}
                    {plan.monthlyPoints > 0
                      ? `每月 ${plan.monthlyPoints} 积分`
                      : `一次性 ${plan.oneTimePoints} 积分`}
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

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-3 mt-6 border-b border-stroke pb-2 font-serif text-base font-semibold tracking-widest">
      {children}
    </h2>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <input
        className="input"
        value={value}
        placeholder={placeholder}
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
