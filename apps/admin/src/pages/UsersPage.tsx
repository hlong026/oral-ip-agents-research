import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { adminApi, type AdminRole } from "../lib/adminHttp";

// 与服务端 CREDIT_CONFIRM_THRESHOLD 对齐：扣减或 |points| 达到该值需二次确认
const CREDIT_CONFIRM_THRESHOLD = 10_000;

// 角色变更仅超管可执行（服务端 403 保护）；user 为纯数据面角色，无管理面权限
const ROLE_OPTIONS: { value: AdminRole; label: string }[] = [
  { value: "user", label: "user · 普通用户" },
  { value: "ops", label: "ops · 运营" },
  { value: "finance", label: "finance · 财务" },
  { value: "auditor", label: "auditor · 审计" },
  { value: "admin", label: "admin · 超管" },
];

export default function UsersPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-users"],
    queryFn: adminApi.listUsers,
  });
  const update = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: { role?: AdminRole; isActive?: boolean };
    }) => adminApi.updateUser(id, body),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });
  const [adjustment, setAdjustment] = useState({
    userId: "",
    points: 0,
    reason: "",
  });
  const adjust = useMutation({
    mutationFn: (confirm: boolean) =>
      adminApi.adjustUserCredits(adjustment.userId, {
        points: adjustment.points,
        reason: adjustment.reason,
        confirm,
      }),
    onSuccess: async () => {
      setAdjustment({ userId: "", points: 0, reason: "" });
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });
  const needsConfirm =
    adjustment.points < 0 ||
    Math.abs(adjustment.points) >= CREDIT_CONFIRM_THRESHOLD;
  const submitAdjustment = () => {
    if (needsConfirm) {
      const message =
        adjustment.points < 0
          ? `确认扣减该用户 ${Math.abs(adjustment.points)} 积分？操作将写入不可变流水。`
          : `确认发放 ${adjustment.points} 大额积分？操作将写入不可变流水。`;
      if (!window.confirm(message)) return;
    }
    adjust.mutate(needsConfirm);
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">用户管理</h1>
        <p className="mt-2 text-sm text-text-3">
          员工和第三方客户共用 user 权限，通过套餐 SKU 与激活渠道区分来源。
        </p>
      </div>
      <section className="glass grid gap-3 p-5 md:grid-cols-[1fr_160px_1fr_auto] md:items-end">
        <label>
          <span className="label">调整用户</span>
          <select
            className="input"
            value={adjustment.userId}
            onChange={(event) =>
              setAdjustment({ ...adjustment, userId: event.target.value })
            }
          >
            <option value="">请选择用户</option>
            {(data?.items ?? []).map((user) => (
              <option key={user.id} value={user.id}>
                {user.nickname} · {user.phone}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="label">积分（可为负）</span>
          <input
            className="input"
            type="number"
            value={adjustment.points}
            onChange={(event) =>
              setAdjustment({
                ...adjustment,
                points: Number(event.target.value),
              })
            }
          />
        </label>
        <label>
          <span className="label">调整原因</span>
          <input
            className="input"
            value={adjustment.reason}
            onChange={(event) =>
              setAdjustment({ ...adjustment, reason: event.target.value })
            }
            placeholder="必填，写入不可变流水"
          />
        </label>
        <button
          className="btn-primary"
          disabled={
            !adjustment.userId ||
            adjustment.points === 0 ||
            adjustment.reason.length < 3 ||
            adjust.isPending
          }
          onClick={submitAdjustment}
        >
          {needsConfirm ? "提交调整（需确认）" : "提交调整"}
        </button>
        {adjust.error instanceof Error && (
          <p className="text-sm text-danger md:col-span-4">
            {adjust.error.message}
          </p>
        )}
      </section>
      <section className="glass overflow-hidden">
        {isLoading && <p className="p-5 text-sm text-text-3">加载中...</p>}
        {error instanceof Error && (
          <p className="p-5 text-sm text-danger">{error.message}</p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-stroke text-left text-text-3">
              <tr>
                <th className="px-4 py-3">用户</th>
                <th className="px-4 py-3">套餐</th>
                <th className="px-4 py-3 text-right">积分</th>
                <th className="px-4 py-3">权限</th>
                <th className="px-4 py-3">状态</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((user) => (
                <tr
                  key={user.id}
                  className="border-b border-stroke/50 last:border-0"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium">{user.nickname}</div>
                    <div className="text-xs text-text-3">{user.phone}</div>
                  </td>
                  <td className="px-4 py-3 text-text-2">
                    {user.planSkuCode || user.planType || "未开通"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {user.balance.toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <select
                      className="input min-w-24 py-1"
                      value={user.role}
                      disabled={update.isPending}
                      onChange={(event) =>
                        update.mutate({
                          id: user.id,
                          body: {
                            role: event.target.value as AdminRole,
                          },
                        })
                      }
                    >
                      {ROLE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      className="btn-ghost"
                      disabled={update.isPending}
                      onClick={() =>
                        update.mutate({
                          id: user.id,
                          body: { isActive: !user.isActive },
                        })
                      }
                    >
                      {user.isActive ? "停用" : "启用"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
