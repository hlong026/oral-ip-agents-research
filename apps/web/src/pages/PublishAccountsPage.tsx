import { HttpError, publishApi } from "@oral/api-client";
import { PLATFORM_NAMES, type Platform, type PublishAccount } from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import PlatformIcon from "../components/PlatformIcon";

interface QrSession {
  platform: Platform;
  ticket: string;
  qrcodeUrl: string;
  status: "waiting" | "success" | "expired";
}

/** 扫码授权弹层（F-502：qrcode 发起 → 2s 轮询 → 成功/过期） */
function QrPanel({ session, onClose, onSuccess }: { session: QrSession; onClose: () => void; onSuccess: () => void }) {
  const [status, setStatus] = useState(session.status);

  useEffect(() => {
    if (status !== "waiting") return;
    const timer = setInterval(async () => {
      try {
        const res = await publishApi.qrcodePoll(session.ticket, session.platform);
        setStatus(res.status);
        if (res.status === "success") {
          clearInterval(timer);
          setTimeout(onSuccess, 800);
        }
      } catch {
        /* 网络抖动时继续轮询 */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [session, status, onSuccess]);

  return (
    <div className="glass-strong flex items-center gap-4 border-brand-from/40 p-4">
      <div className="flex h-28 w-28 shrink-0 items-center justify-center rounded-xl bg-white p-2">
        {session.qrcodeUrl ? (
          <img src={session.qrcodeUrl} alt="授权二维码" className="h-full w-full object-contain" />
        ) : (
          <span className="text-4xl">▦</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-medium">
          <PlatformIcon platform={session.platform} size={18} /> 绑定{PLATFORM_NAMES[session.platform]}账号
        </div>
        <div className="mt-1 text-sm text-text-3">
          {status === "waiting" && "请使用手机 App 扫码，并在手机上确认授权"}
          {status === "success" && <span className="text-success">✓ 授权成功，正在写入账号…</span>}
          {status === "expired" && <span className="text-warning">二维码已过期，请重新发起</span>}
        </div>
      </div>
      <button className="btn-ghost px-3 py-1 text-xs" onClick={onClose}>
        取消
      </button>
    </div>
  );
}

/** 账号管理（F-501/502：扫码授权、登录态红色告警、一键重新授权、解绑） */
export default function PublishAccountsPage() {
  const queryClient = useQueryClient();
  const [qr, setQr] = useState<QrSession | null>(null);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const startingRef = useRef(false);

  const { data: accounts, refetch } = useQuery({
    queryKey: ["publish-accounts"],
    queryFn: () => publishApi.accounts(),
    refetchInterval: 30_000,
  });

  const list = accounts ?? [];
  const expired = list.filter((a) => a.status === "expired");

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["publish-accounts"] });
    await refetch();
  };

  const startBind = async (platform: Platform) => {
    if (startingRef.current) return;
    startingRef.current = true;
    setError("");
    try {
      const res = await publishApi.qrcodeStart(platform);
      setQr({ platform, ticket: res.ticket, qrcodeUrl: res.qrcodeUrl, status: "waiting" });
    } catch (e) {
      setError(e instanceof HttpError ? e.body.message : "发起扫码授权失败");
    } finally {
      startingRef.current = false;
    }
  };

  const reauth = async (account: PublishAccount) => {
    setBusyId(account.id);
    setError("");
    try {
      const res = await publishApi.reauth(account.id);
      setQr({ platform: account.platform, ticket: res.ticket, qrcodeUrl: res.qrcodeUrl, status: "waiting" });
    } catch (e) {
      setError(e instanceof HttpError ? e.body.message : "发起重新授权失败");
    } finally {
      setBusyId("");
    }
  };

  const unbind = async (account: PublishAccount) => {
    setBusyId(account.id);
    setError("");
    try {
      await publishApi.deleteAccount(account.id);
      await refresh();
    } catch (e) {
      setError(e instanceof HttpError ? e.body.message : "解绑失败");
    } finally {
      setBusyId("");
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">账号管理</h1>
          <p className="mt-1 text-sm text-text-3">平台账号绑定 · 登录态巡检 · 授权续期（F-501/502）</p>
        </div>
        <span className="chip text-[11px]">每日 06:00 自动巡检登录态</span>
      </div>

      {/* 登录态失效红色告警 */}
      {expired.length > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-card border border-danger/40 bg-danger/10 px-4 py-3">
          <span className="text-sm text-danger">
            ⚠ {expired.map((a) => `${a.platformName}账号「${a.nickname}」`).join("、")}登录态已过期，关联发布任务被阻塞。
          </span>
          <button className="btn-primary px-3 py-1 text-xs" disabled={busyId === expired[0]!.id} onClick={() => void reauth(expired[0]!)}>
            扫码重新授权
          </button>
        </div>
      )}
      {error && <div className="rounded-card border border-danger/30 bg-danger/10 px-4 py-2 text-sm text-danger">{error}</div>}

      {/* 扫码授权面板 */}
      {qr && (
        <QrPanel
          session={qr}
          onClose={() => setQr(null)}
          onSuccess={() => {
            setQr(null);
            void refresh();
          }}
        />
      )}

      {/* 已绑定账号 */}
      <div className="glass p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">已绑定账号（{list.length}）</h2>
          <span className="text-xs text-text-3">Cookie 加密存 PG · 会话态 Redis</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-stroke text-left text-xs text-text-3">
                <th className="pb-2 pr-3 font-medium">平台</th>
                <th className="pb-2 pr-3 font-medium">账号</th>
                <th className="pb-2 pr-3 font-medium">登录态</th>
                <th className="pb-2 pr-3 font-medium">绑定时间</th>
                <th className="pb-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {list.map((a) => (
                <tr key={a.id} className="border-b border-stroke/50 last:border-0">
                  <td className="py-2.5 pr-3">
                    <span className="chip text-[11px]">
                      <PlatformIcon platform={a.platform} size={14} /> {a.platformName}
                    </span>
                  </td>
                  <td className="py-2.5 pr-3 font-medium">{a.nickname}</td>
                  <td className="py-2.5 pr-3">
                    {a.status === "active" ? (
                      <span className="chip border-success/40 text-[11px] text-success">正常</span>
                    ) : (
                      <span className="chip border-danger/40 text-[11px] text-danger">已过期</span>
                    )}
                  </td>
                  <td className="py-2.5 pr-3 text-xs text-text-3">{new Date(a.createdAt).toLocaleDateString("zh-CN")}</td>
                  <td className="py-2.5">
                    <div className="flex gap-1.5">
                      {a.status === "expired" ? (
                        <button className="btn-primary px-2.5 py-0.5 text-xs" disabled={busyId === a.id} onClick={() => void reauth(a)}>
                          重新授权
                        </button>
                      ) : (
                        <button className="btn-ghost px-2.5 py-0.5 text-xs" disabled={busyId === a.id} onClick={() => void reauth(a)}>
                          续期
                        </button>
                      )}
                      <button className="btn-ghost px-2.5 py-0.5 text-xs" disabled={busyId === a.id} onClick={() => void unbind(a)}>
                        解绑
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {list.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-text-3">
                    暂无绑定账号，先在下方扫码绑定一个平台账号
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid items-start gap-4 md:grid-cols-2">
        {/* 绑定新账号 */}
        <div className="glass p-5">
          <h2 className="mb-4 font-medium">绑定新账号</h2>
          <div className="flex flex-wrap gap-2.5">
            {(Object.keys(PLATFORM_NAMES) as Platform[]).map((p) => (
              <button key={p} className="btn-ghost" onClick={() => void startBind(p)}>
                <PlatformIcon platform={p} size={16} /> 绑定{PLATFORM_NAMES[p]}
              </button>
            ))}
          </div>
          <div className="mt-4 rounded-xl border border-info/30 bg-info/10 p-3 text-xs text-info">
            ℹ 绑定时使用手机扫码，Cookie 仅保存在您的账户中并加密存储，可随时解绑清除。
          </div>
        </div>

        {/* 巡检设置 */}
        <div className="glass p-5">
          <h2 className="mb-4 font-medium">登录态巡检与提醒</h2>
          <div className="space-y-2.5 text-sm">
            <div className="flex items-center justify-between">
              <span>每日自动巡检</span>
              <span className="chip border-success/40 text-[11px] text-success">已开启 · 06:00</span>
            </div>
            <div className="flex items-center justify-between">
              <span>到期前提醒</span>
              <span className="chip border-success/40 text-[11px] text-success">提前 3 天 · 站内信</span>
            </div>
            <div className="flex items-center justify-between">
              <span>过期自动暂停发布</span>
              <span className="chip border-success/40 text-[11px] text-success">已开启</span>
            </div>
            <div className="flex items-center justify-between">
              <span>解绑后保留历史数据</span>
              <span className="chip text-[11px]">保留 90 天</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
