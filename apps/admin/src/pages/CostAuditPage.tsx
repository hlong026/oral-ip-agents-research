import { useQuery } from "@tanstack/react-query";
import { adminApi } from "../lib/adminHttp";

export default function CostAuditPage() {
  const costs = useQuery({
    queryKey: ["admin-cost-analysis"],
    queryFn: adminApi.costAnalysis,
  });
  const audit = useQuery({
    queryKey: ["admin-audit"],
    queryFn: adminApi.audit,
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">成本与审计</h1>
        <p className="mt-2 text-sm text-text-3">
          供应商内部成本只在管理端展示；SKU、价格、Provider 与用户变更均可追溯。
        </p>
      </div>
      <section className="glass overflow-hidden">
        <div className="border-b border-stroke px-5 py-4">
          <h2 className="font-medium">模块单位经济性</h2>
          <p className="mt-1 text-xs text-text-3">
            价格版本：{costs.data?.priceVersion || "未发布"}
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-stroke text-left text-text-3">
              <tr>
                <th className="px-4 py-3">模块</th>
                <th className="px-4 py-3 text-right">用户积分</th>
                <th className="px-4 py-3 text-right">供应商成本</th>
                <th className="px-4 py-3 text-right">目标毛利</th>
              </tr>
            </thead>
            <tbody>
              {(costs.data?.items ?? []).map((item) => (
                <tr
                  key={item.module}
                  className="border-b border-stroke/50 last:border-0"
                >
                  <td className="px-4 py-3">{item.displayName}</td>
                  <td className="px-4 py-3 text-right font-mono">
                    {item.pointsPerUnit}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    ¥{(item.internalCostCentsPerUnit / 100).toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {(item.targetMarginBps / 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="glass overflow-hidden">
        <div className="border-b border-stroke px-5 py-4">
          <h2 className="font-medium">管理员操作审计</h2>
        </div>
        <div className="divide-y divide-stroke/50">
          {(audit.data?.items ?? []).map((item) => (
            <article
              key={item.id}
              className="grid gap-1 px-5 py-3 text-sm md:grid-cols-[180px_180px_1fr]"
            >
              <span className="text-text-3">
                {new Date(item.createdAt).toLocaleString("zh-CN")}
              </span>
              <span className="font-medium">{item.event}</span>
              <span className="break-all text-text-2">{item.detail}</span>
            </article>
          ))}
          {!audit.isLoading && (audit.data?.items.length ?? 0) === 0 && (
            <p className="p-5 text-sm text-text-3">暂无审计记录。</p>
          )}
        </div>
      </section>
    </div>
  );
}
