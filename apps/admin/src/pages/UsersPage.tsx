import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { adminApi } from "../lib/adminHttp";
import UserUsageDrawer from "./users/UsageDrawer";

const SOURCE_LABEL: Record<string, string> = {
  "desktop-hw": "桌面端（硬件码）",
  web: "网页端",
};

function DeviceDrawer({
  userId,
  nickname,
  onClose,
}: {
  userId: string;
  nickname: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-user-devices", userId],
    queryFn: () => adminApi.listUserDevices(userId),
  });
  const unbindOne = useMutation({
    mutationFn: (deviceId: string) =>
      adminApi.unbindSingleDevice(userId, deviceId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["admin-user-devices", userId],
      });
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });
  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40"
      onClick={onClose}
    >
      <aside
        className="glass h-full w-full max-w-md space-y-4 overflow-y-auto p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">{nickname} 的设备</h2>
            <p className="text-xs text-text-3">
              已绑定 {data?.items.length ?? 0} / 上限 {data?.limit ?? "-"}
            </p>
          </div>
          <button className="btn-ghost" onClick={onClose}>
            关闭
          </button>
        </div>
        {isLoading && <p className="text-sm text-text-3">加载中...</p>}
        {error instanceof Error && (
          <p className="text-sm text-danger">{error.message}</p>
        )}
        {unbindOne.error instanceof Error && (
          <p className="text-sm text-danger">{unbindOne.error.message}</p>
        )}
        {(data?.items ?? []).map((device) => (
          <div
            key={device.id}
            className="flex items-center justify-between rounded-lg border border-stroke/60 p-3"
          >
            <div>
              <div className="text-sm font-medium">
                {device.deviceName || "未命名设备"}
                <span className="ml-2 text-xs text-text-3">
                  {SOURCE_LABEL[device.source] ?? device.source}
                </span>
              </div>
              <div className="mt-1 font-mono text-xs text-text-3">
                {device.deviceKey.slice(0, 12)}…
              </div>
              <div className="mt-1 text-xs text-text-3">
                最近活跃 {new Date(device.lastSeenAt).toLocaleString()}
              </div>
            </div>
            <button
              className="btn-ghost"
              disabled={unbindOne.isPending}
              onClick={() => {
                if (
                  window.confirm(`确认解绑该设备？解绑后该设备登录态立即失效。`)
                ) {
                  unbindOne.mutate(device.id);
                }
              }}
            >
              解绑
            </button>
          </div>
        ))}
        {!isLoading && (data?.items ?? []).length === 0 && (
          <p className="text-sm text-text-3">暂无绑定设备</p>
        )}
      </aside>
    </div>
  );
}

function SecurityPolicyCard() {
  const queryClient = useQueryClient();
  const { data: limit, isLoading } = useQuery({
    queryKey: ["device-bind-limit"],
    queryFn: adminApi.getDeviceBindLimit,
  });
  const [draft, setDraft] = useState<number | null>(null);
  const save = useMutation({
    mutationFn: (value: number) => adminApi.saveDeviceBindLimit(value),
    onSuccess: async () => {
      setDraft(null);
      await queryClient.invalidateQueries({ queryKey: ["device-bind-limit"] });
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });
  const value = draft ?? limit ?? 1;
  return (
    <section className="glass flex flex-wrap items-end gap-3 p-5">
      <div className="mr-auto">
        <h2 className="text-base font-semibold">安全策略</h2>
        <p className="mt-1 text-xs text-text-3">
          每个激活码可同时绑定的设备数（1~10），超出后新设备登录需管理员审批。
        </p>
      </div>
      <label>
        <span className="label">设备绑定上限</span>
        <input
          className="input w-28"
          type="number"
          min={1}
          max={10}
          value={value}
          disabled={isLoading}
          onChange={(event) => setDraft(Number(event.target.value))}
        />
      </label>
      <button
        className="btn-primary"
        disabled={
          save.isPending ||
          draft === null ||
          !Number.isInteger(draft) ||
          draft < 1 ||
          draft > 10
        }
        onClick={() => draft !== null && save.mutate(draft)}
      >
        保存
      </button>
      {save.error instanceof Error && (
        <p className="w-full text-sm text-danger">{save.error.message}</p>
      )}
    </section>
  );
}

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
      body: { role?: "user" | "admin"; isActive?: boolean };
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
    mutationFn: () =>
      adminApi.adjustUserCredits(adjustment.userId, {
        points: adjustment.points,
        reason: adjustment.reason,
      }),
    onSuccess: async () => {
      setAdjustment({ userId: "", points: 0, reason: "" });
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });
  const unbind = useMutation({
    mutationFn: (id: string) => adminApi.unbindDevice(id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });
  const [deviceDrawer, setDeviceDrawer] = useState<{
    userId: string;
    nickname: string;
  } | null>(null);
  const [usageDrawer, setUsageDrawer] = useState<{
    userId: string;
    userName: string;
    userPhone: string | null;
    activationCodeMasked: string | null;
    balance: number;
  } | null>(null);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">用户管理</h1>
        <p className="mt-2 text-sm text-text-3">
          员工和第三方客户共用 user 权限，通过套餐 SKU 与激活渠道区分来源。
        </p>
      </div>
      <SecurityPolicyCard />
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
                {user.nickname} · {user.phone || "激活码用户"}
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
          onClick={() => adjust.mutate()}
        >
          提交调整
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
                <th className="px-4 py-3">调用记录</th>
                <th className="px-4 py-3">设备</th>
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
                    <div className="text-xs text-text-3">
                      {user.phone || user.activationCodeMasked || "激活码用户"}
                    </div>
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
                            role: event.target.value as "user" | "admin",
                          },
                        })
                      }
                    >
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      className="btn-ghost text-xs"
                      onClick={() =>
                        setUsageDrawer({
                          userId: user.id,
                          userName: user.nickname,
                          userPhone: user.phone,
                          activationCodeMasked:
                            user.activationCodeMasked ?? null,
                          balance: user.balance,
                        })
                      }
                    >
                      查看
                    </button>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button
                        className="btn-ghost font-mono"
                        title="查看设备列表"
                        onClick={() =>
                          setDeviceDrawer({
                            userId: user.id,
                            nickname: user.nickname,
                          })
                        }
                      >
                        {user.deviceCount ?? (user.deviceBound ? 1 : 0)}/
                        {user.deviceLimit ?? 1}
                      </button>
                      {(user.deviceCount ?? 0) > 0 && (
                        <button
                          className="btn-ghost"
                          disabled={unbind.isPending}
                          onClick={() => {
                            if (
                              window.confirm(
                                `确认解绑 ${user.nickname} 的全部设备？解绑后其登录态将失效，下次登录自动绑定新设备。`,
                              )
                            ) {
                              unbind.mutate(user.id);
                            }
                          }}
                        >
                          全部解绑
                        </button>
                      )}
                    </div>
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
      {deviceDrawer && (
        <DeviceDrawer
          userId={deviceDrawer.userId}
          nickname={deviceDrawer.nickname}
          onClose={() => setDeviceDrawer(null)}
        />
      )}
      {usageDrawer && (
        <UserUsageDrawer
          userId={usageDrawer.userId}
          userName={usageDrawer.userName}
          userPhone={usageDrawer.userPhone}
          activationCodeMasked={usageDrawer.activationCodeMasked}
          balance={usageDrawer.balance}
          onClose={() => setUsageDrawer(null)}
        />
      )}
    </div>
  );
}
