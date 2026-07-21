import { activationApi, catalogApi, HttpError } from "@oral/api-client";
import { useQuota } from "@oral/stores";
import type { BillingUnit, ModulePrice, PlanSku } from "@oral/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const UNIT_LABELS: Record<BillingUnit, string> = {
  per_action: "每次",
  per_minute: "每分钟",
  per_second: "每秒",
  per_1k_chars: "每 1000 字",
  per_1k_tokens: "每 1000 Token",
  per_image: "每张",
  per_asset: "每个素材",
};

function formatPrice(cents?: number | null) {
  if (cents === null || cents === undefined) return "联系购买";
  if (cents === 0) return "免费";
  return `¥${(cents / 100).toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
}

function planPoints(plan: PlanSku) {
  if (plan.monthlyPoints > 0)
    return `每月 ${plan.monthlyPoints.toLocaleString()} 积分`;
  if (plan.oneTimePoints > 0)
    return `${plan.oneTimePoints.toLocaleString()} 积分`;
  return "不含积分";
}

function PlanCard({ plan, current }: { plan: PlanSku; current: boolean }) {
  return (
    <article className="glass card-hover flex h-full flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-text-1">{plan.name}</h2>
          {plan.subtitle && (
            <p className="mt-1 text-sm text-text-3">{plan.subtitle}</p>
          )}
        </div>
        {(current || plan.badge) && (
          <span className="rounded-full bg-brand-from/20 px-2.5 py-1 text-xs font-medium text-brand-to">
            {current ? "当前套餐" : plan.badge}
          </span>
        )}
      </div>

      <div className="mt-4">
        <span className="text-3xl font-black text-grad">
          {formatPrice(plan.displayPriceCents)}
        </span>
        {plan.listPriceCents &&
          plan.listPriceCents > (plan.displayPriceCents ?? 0) && (
            <span className="ml-2 text-sm text-text-3 line-through">
              {formatPrice(plan.listPriceCents)}
            </span>
          )}
      </div>

      <div className="mt-3 grid gap-2 text-sm text-text-2">
        <span>
          服务期：
          {plan.durationDays > 0 ? `${plan.durationDays} 天` : "不延长服务期"}
        </span>
        <span>积分：{planPoints(plan)}</span>
        {plan.maxConcurrency ? (
          <span>并发任务：{plan.maxConcurrency} 个</span>
        ) : null}
        {plan.maxResolution ? (
          <span>最高导出：{plan.maxResolution}</span>
        ) : null}
      </div>

      {plan.description && (
        <p className="mt-3 text-sm text-text-3">{plan.description}</p>
      )}

      <ul className="mt-4 flex-1 space-y-2 text-sm text-text-2">
        {plan.entitlements.slice(0, 6).map((feature) => (
          <li key={feature} className="flex gap-2">
            <span className="text-success">✓</span>
            <span>{feature}</span>
          </li>
        ))}
      </ul>

      {plan.purchaseInstructions && (
        <div className="mt-4 rounded-xl bg-white/5 px-3 py-2 text-xs text-text-3">
          {plan.purchaseInstructions}
        </div>
      )}
    </article>
  );
}

function ModulePriceRow({ price }: { price: ModulePrice }) {
  return (
    <tr className="border-b border-stroke/40 last:border-0">
      <td className="px-5 py-3">
        <div className="font-medium text-text-1">{price.displayName}</div>
        {price.publicDescription && (
          <div className="mt-0.5 text-xs text-text-3">
            {price.publicDescription}
          </div>
        )}
      </td>
      <td className="px-5 py-3 text-text-2">
        {UNIT_LABELS[price.billingUnit]}
      </td>
      <td className="px-5 py-3 text-right font-mono text-text-1">
        {price.pointsPerUnit.toLocaleString()} 点
      </td>
      <td className="px-5 py-3 text-right text-text-3">
        {price.minimumPoints > 0 ? `${price.minimumPoints} 点起` : "—"}
      </td>
    </tr>
  );
}

function RedeemCard() {
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const queryClient = useQueryClient();
  const reloadQuota = useQuota((s) => s.load);

  const redeem = useMutation({
    mutationFn: () => activationApi.redeem(code.trim()),
    onSuccess: async (result) => {
      setMessage(
        `兑换成功，已到账 ${result.quotaGranted.toLocaleString()} 积分，当前余额 ${result.newBalance.toLocaleString()}。`,
      );
      setCode("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["subscription"] }),
        queryClient.invalidateQueries({ queryKey: ["quota"] }),
        reloadQuota(),
      ]);
    },
    onError: (err) => {
      setMessage(
        err instanceof HttpError ? err.body.message : "兑换失败，请稍后再试",
      );
    },
  });

  return (
    <section className="glass p-5">
      <h2 className="text-lg font-bold">激活码 / 续费码兑换</h2>
      <p className="mt-1 text-sm text-text-3">
        输入管理员或代理商提供的激活码，可开通套餐、续费或补充积分。
      </p>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <input
          className="input flex-1 font-mono tracking-wider"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="ORAL-XXXX-XXXX-XXXX-XXXX-XXXX"
        />
        <button
          className="btn-primary px-5"
          disabled={!code.trim() || redeem.isPending}
          onClick={() => redeem.mutate()}
        >
          {redeem.isPending ? "兑换中…" : "立即兑换"}
        </button>
      </div>
      {message && (
        <div className="mt-3 rounded-xl border border-stroke bg-white/5 px-3 py-2 text-sm text-text-2">
          {message}
        </div>
      )}
    </section>
  );
}

export default function PricingPage() {
  const { data: plans, isLoading: plansLoading } = useQuery({
    queryKey: ["catalog", "plans"],
    queryFn: () => catalogApi.plans(),
  });
  const { data: priceCatalog, isLoading: pricesLoading } = useQuery({
    queryKey: ["catalog", "module-prices"],
    queryFn: () => catalogApi.modulePrices(),
  });
  const { data: subscription } = useQuery({
    queryKey: ["subscription"],
    queryFn: () => activationApi.subscription(),
  });

  const publicPlans = (plans ?? [])
    .filter((plan) => plan.audience === "public")
    .sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0));
  const visiblePrices = priceCatalog?.items ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-bold">套餐与积分</h1>
          <p className="mt-1 text-sm text-text-3">
            套餐决定服务期限和月度积分，模块价格决定每次创作会消耗多少积分。
          </p>
        </div>
        {priceCatalog?.updatedAt && (
          <span className="text-xs text-text-3">
            价格版本 {priceCatalog.version} ·{" "}
            {new Date(priceCatalog.updatedAt).toLocaleDateString("zh-CN")}
          </span>
        )}
      </div>

      <RedeemCard />

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">可用套餐</h2>
          <span className="text-xs text-text-3">内部套餐不会在用户端展示</span>
        </div>
        {plansLoading ? (
          <div className="glass p-6 text-center text-sm text-text-3">
            套餐加载中…
          </div>
        ) : publicPlans.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {publicPlans.map((plan) => (
              <PlanCard
                key={`${plan.code}:${plan.version}`}
                plan={plan}
                current={subscription?.planSkuCode === plan.code}
              />
            ))}
          </div>
        ) : (
          <div className="glass p-6 text-center text-sm text-text-3">
            暂无已发布套餐，请联系管理员获取激活码。
          </div>
        )}
      </section>

      <section className="glass overflow-hidden">
        <div className="border-b border-stroke px-5 py-3">
          <h2 className="font-medium">模块积分价格</h2>
          <p className="mt-1 text-xs text-text-3">
            这里展示用户可见积分价格，不包含供应商成本和平台毛利数据。
          </p>
        </div>
        {pricesLoading ? (
          <div className="p-6 text-center text-sm text-text-3">价格加载中…</div>
        ) : visiblePrices.length > 0 ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-stroke text-left text-xs text-text-3">
                <th className="px-5 py-2.5 font-medium">模块</th>
                <th className="px-5 py-2.5 font-medium">计费单位</th>
                <th className="px-5 py-2.5 text-right font-medium">单价</th>
                <th className="px-5 py-2.5 text-right font-medium">最低消费</th>
              </tr>
            </thead>
            <tbody>
              {visiblePrices.map((price) => (
                <ModulePriceRow key={price.module} price={price} />
              ))}
            </tbody>
          </table>
        ) : (
          <div className="p-6 text-center text-sm text-text-3">
            暂无已发布模块价格。
          </div>
        )}
      </section>
    </div>
  );
}
