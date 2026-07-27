import { activationApi, billingApi } from "@oral/api-client";
import { useSession } from "@oral/stores";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

/** 账号与额度（F-602：额度查询 / 用量明细 / CSV 导出） */
export default function AccountPage() {
  const { user } = useSession();
  const [page, setPage] = useState(1);
  const [searchParams] = useSearchParams();
  const planExpired = searchParams.get("reason") === "plan_expired";
  const { data: quota } = useQuery({
    queryKey: ["quota"],
    queryFn: () => billingApi.quota(),
  });
  const { data: subscription } = useQuery({
    queryKey: ["subscription"],
    queryFn: () => activationApi.subscription(),
  });
  const { data: usage } = useQuery({
    queryKey: ["usage", page],
    queryFn: () => billingApi.usage(page, 10),
  });

  const usedPct =
    quota && quota.total > 0
      ? Math.round((quota.usedThisMonth / quota.total) * 100)
      : 0;

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <h1 className="text-xl font-bold">账号与额度</h1>

      {planExpired && (
        <div className="flex items-center justify-between rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
          <span>套餐已到期，兑换新的激活码即可继续使用</span>
          <Link to="/pricing" className="btn-primary px-3 py-1 text-xs">
            去兑换
          </Link>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {/* 用户信息卡 */}
        <div className="glass p-5">
          <div className="flex items-center gap-4">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-grad text-2xl font-bold text-white">
              {user?.avatarChar || "U"}
            </span>
            <div>
              <div className="text-lg font-bold">{user?.nickname}</div>
              <div className="text-sm text-text-3">
                {user?.deviceBound ? "已绑定本设备" : "未绑定设备"}
              </div>
            </div>
          </div>
          <div className="mt-4 grid gap-1 border-t border-stroke pt-3 text-xs text-text-3">
            <span>
              开通时间：
              {user?.createdAt
                ? new Date(user.createdAt).toLocaleDateString("zh-CN")
                : "—"}
            </span>
            <span>
              设备绑定：
              {user?.deviceBound
                ? "已绑定（换设备需联系管理员解绑）"
                : "未绑定，下次登录自动绑定"}
            </span>
          </div>
        </div>

        {/* 套餐与额度卡 */}
        <div className="glass p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm text-text-2">当前套餐</div>
              <div className="mt-1 text-lg font-bold text-text-1">
                {subscription?.planName || subscription?.planType || "未激活"}
              </div>
            </div>
            <Link to="/pricing" className="btn-ghost px-3 py-1 text-xs">
              续费/充值
            </Link>
          </div>
          <div className="mt-3 grid gap-1 text-xs text-text-3">
            <span>
              到期时间：
              {subscription?.planExpiresAt
                ? new Date(subscription.planExpiresAt).toLocaleDateString(
                    "zh-CN",
                  )
                : "—"}
            </span>
            <span>
              下次发放：
              {subscription?.nextGrantAt
                ? new Date(subscription.nextGrantAt).toLocaleDateString("zh-CN")
                : "—"}
            </span>
            {(subscription?.monthlyPoints ?? 0) > 0 && (
              <span>
                月度积分：{subscription!.monthlyPoints!.toLocaleString()} 点
              </span>
            )}
          </div>

          <div className="mt-4 text-sm text-text-2">算力余额</div>
          <div className="text-grad mt-1 text-3xl font-black">
            {(quota?.balance ?? 0).toLocaleString()}
            <span className="ml-1 text-sm font-normal text-text-3">点</span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full rounded-full bg-brand-grad-x"
              style={{ width: `${100 - usedPct}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-xs text-text-3">
            <span>
              本月已用 {(quota?.usedThisMonth ?? 0).toLocaleString()} 点
            </span>
            <span>累计 {(quota?.total ?? 0).toLocaleString()} 点</span>
          </div>
        </div>
      </div>

      {/* 用量明细 */}
      <div className="glass overflow-hidden">
        <div className="flex items-center justify-between border-b border-stroke px-5 py-3">
          <span className="font-medium">用量明细</span>
          <a
            href={billingApi.exportCsvUrl()}
            className="btn-ghost px-3 py-1 text-xs"
            download
          >
            导出 CSV
          </a>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-stroke text-left text-xs text-text-3">
              <th className="px-5 py-2.5 font-medium">时间</th>
              <th className="px-5 py-2.5 font-medium">步骤</th>
              <th className="px-5 py-2.5 font-medium">通道</th>
              <th className="px-5 py-2.5 font-medium">分辨率</th>
              <th className="px-5 py-2.5 text-right font-medium">点数</th>
            </tr>
          </thead>
          <tbody>
            {(usage?.items ?? []).map((u) => (
              <tr
                key={u.id}
                className="border-b border-stroke/40 last:border-0"
              >
                <td className="px-5 py-2.5 text-text-2">
                  {new Date(u.createdAt).toLocaleString("zh-CN")}
                </td>
                <td className="px-5 py-2.5">{u.step}</td>
                <td className="px-5 py-2.5">
                  <span className="chip">
                    {u.compute === "cloud" ? "云端" : "本地"}
                  </span>
                </td>
                <td className="px-5 py-2.5 text-text-3">{u.resolution}</td>
                <td
                  className={`px-5 py-2.5 text-right font-mono ${u.points < 0 ? "text-success" : "text-text-1"}`}
                >
                  {u.points > 0
                    ? `-${u.points}`
                    : u.points === 0
                      ? "0（免扣）"
                      : `+${-u.points}（退还）`}
                </td>
              </tr>
            ))}
            {(usage?.items ?? []).length === 0 && (
              <tr>
                <td colSpan={5} className="px-5 py-8 text-center text-text-3">
                  暂无用量记录
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {(usage?.total ?? 0) > 10 && (
          <div className="flex items-center justify-end gap-2 border-t border-stroke px-5 py-3 text-sm">
            <button
              className="btn-ghost px-3 py-1"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              上一页
            </button>
            <span className="text-text-3">{page}</span>
            <button
              className="btn-ghost px-3 py-1"
              disabled={page * 10 >= (usage?.total ?? 0)}
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
