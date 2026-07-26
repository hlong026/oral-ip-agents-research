import {
  HttpError,
  imApi,
  publishApi,
  type IMAutomationStatus,
  type IMListenerStatus,
} from "@oral/api-client";
import {
  PLATFORM_NAMES,
  PUBLISH_PLATFORMS,
  type Platform,
  type PublishAccount,
} from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Info, PenLine, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import PlatformIcon from "../components/PlatformIcon";
import { IM_ENABLED } from "../config/features";

interface QrSession {
  platform: Platform;
  ticket: string;
  qrcodeUrl: string;
  status: "starting" | "waiting" | "success" | "expired";
}

/** 扫码授权弹层（F-502：qrcode 发起 → 2s 轮询 → 成功/过期；等待中同步刷新后的新二维码） */
function QrPanel({
  session,
  onClose,
  onSuccess,
}: {
  session: QrSession;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [status, setStatus] = useState(session.status);
  const [qrUrl, setQrUrl] = useState(session.qrcodeUrl);
  const [statusMessage, setStatusMessage] = useState("");

  useEffect(() => {
    if (status !== "waiting") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const res = await publishApi.qrcodePoll(
          session.ticket,
          session.platform,
        );
        if (cancelled) return;
        // 平台二维码过期后后端会自动刷新，轮询拿到新图立即替换
        if (res.qrcodeUrl) setQrUrl(res.qrcodeUrl);
        if (res.message) setStatusMessage(res.message);
        setStatus(res.status);
      } catch {
        /* 网络抖动时继续轮询 */
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 2000);
    };

    timer = setTimeout(() => void poll(), 2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [session.platform, session.ticket, status]);

  useEffect(() => {
    if (status !== "success") return;
    const timer = setTimeout(onSuccess, 800);
    return () => clearTimeout(timer);
  }, [status, onSuccess]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`添加${PLATFORM_NAMES[session.platform]}账号`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <div className="glass-strong flex w-full max-w-md items-center gap-4 border-brand-from/40 p-5 shadow-2xl">
        <div className="flex h-28 w-28 shrink-0 items-center justify-center rounded-xl bg-white p-2">
          {qrUrl ? (
            <img
              src={qrUrl}
              alt="授权二维码"
              className="h-full w-full object-contain"
            />
          ) : (
            <span className="text-center text-sm text-slate-500">
              {status === "starting" ? "正在生成二维码…" : "二维码加载中…"}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-medium">
            <PlatformIcon platform={session.platform} size={18} /> 绑定
            {PLATFORM_NAMES[session.platform]}账号
          </div>
          <div className="mt-1 text-sm text-text-3">
            {status === "starting" && "正在连接平台并生成二维码，请稍候"}
            {status === "waiting" &&
              "请使用手机 App 扫码，并按平台提示完成授权（二维码过期会自动刷新）"}
            {status === "success" && (
              <span className="inline-flex items-center gap-1 text-success">
                <Check className="h-3.5 w-3.5" /> 授权成功，正在写入账号…
              </span>
            )}
            {status === "expired" && (
              <span className="text-warning">
                {statusMessage || "授权未完成或二维码已过期，请关闭后重新发起"}
              </span>
            )}
          </div>
        </div>
        <button className="btn-ghost px-3 py-1 text-xs" onClick={onClose}>
          取消
        </button>
      </div>
    </div>
  );
}

/** 账号管理（F-501/502：扫码授权、登录态红色告警、一键重新授权、解绑） */
export default function PublishAccountsPage() {
  const queryClient = useQueryClient();
  const [qr, setQr] = useState<QrSession | null>(null);
  const [busyId, setBusyId] = useState("");
  const [editingId, setEditingId] = useState("");
  const [error, setError] = useState("");
  const startingRef = useRef(false);
  const qrRequestRef = useRef(0);

  const { data: accounts } = useQuery({
    queryKey: ["publish-accounts"],
    queryFn: () => publishApi.accounts(),
    refetchInterval: 30_000,
  });
  const { data: capabilities } = useQuery({
    queryKey: ["publish-capabilities"],
    queryFn: () => publishApi.capabilities(),
  });

  const list = accounts ?? [];
  const expired = list.filter((a) => a.status === "expired");

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["publish-accounts"] });
  }, [queryClient]);

  const handleQrSuccess = useCallback(() => {
    setQr(null);
    void refresh();
  }, [refresh]);

  const closeQr = useCallback(() => {
    qrRequestRef.current += 1;
    startingRef.current = false;
    setQr(null);
  }, []);

  const startBind = async (platform: Platform) => {
    if (startingRef.current) return;
    startingRef.current = true;
    const requestId = ++qrRequestRef.current;
    setError("");
    setQr({ platform, ticket: "", qrcodeUrl: "", status: "starting" });
    try {
      const res = await publishApi.qrcodeStart(platform);
      if (requestId !== qrRequestRef.current) return;
      setQr({
        platform,
        ticket: res.ticket,
        qrcodeUrl: res.qrcodeUrl,
        status: "waiting",
      });
    } catch (e) {
      if (requestId !== qrRequestRef.current) return;
      setQr(null);
      setError(e instanceof HttpError ? e.body.message : "发起扫码授权失败");
    } finally {
      if (requestId === qrRequestRef.current) startingRef.current = false;
    }
  };

  const reauth = async (account: PublishAccount) => {
    setBusyId(account.id);
    const requestId = ++qrRequestRef.current;
    setError("");
    setQr({
      platform: account.platform,
      ticket: "",
      qrcodeUrl: "",
      status: "starting",
    });
    try {
      const res = await publishApi.reauth(account.id);
      if (requestId !== qrRequestRef.current) return;
      setQr({
        platform: account.platform,
        ticket: res.ticket,
        qrcodeUrl: res.qrcodeUrl,
        status: "waiting",
      });
    } catch (e) {
      if (requestId !== qrRequestRef.current) return;
      setQr(null);
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

  /** 行内重命名（多账号辨识：昵称提取失败或与平台同名时手动标记） */
  const saveRename = async (accountId: string, name: string) => {
    const cleaned = name.trim();
    setEditingId("");
    if (!cleaned) return;
    const target = list.find((x) => x.id === accountId);
    if (target && cleaned === target.nickname) return;
    setBusyId(accountId);
    setError("");
    try {
      await publishApi.renameAccount(accountId, cleaned);
      await refresh();
    } catch (e) {
      setError(e instanceof HttpError ? e.body.message : "重命名失败");
    } finally {
      setBusyId("");
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">账号管理</h1>
          <p className="mt-1 text-sm text-text-3">
            平台账号绑定 · 登录态巡检 · 授权续期（F-501/502）
          </p>
        </div>
        <span className="chip text-[11px]">按系统配置自动巡检登录态</span>
      </div>

      {/* 登录态失效红色告警 */}
      {expired.length > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-card border border-danger/40 bg-danger/10 px-4 py-3">
          <span className="flex items-center gap-1.5 text-sm text-danger">
            <TriangleAlert className="h-4 w-4 shrink-0" />
            <span>
              {expired
                .map((a) => `${a.platformName}账号「${a.nickname}」`)
                .join("、")}
              登录态已过期，关联发布任务被阻塞。
            </span>
          </span>
          <button
            className="btn-primary px-3 py-1 text-xs"
            disabled={busyId === expired[0]!.id}
            onClick={() => void reauth(expired[0]!)}
          >
            扫码重新授权
          </button>
        </div>
      )}
      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/10 px-4 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      {/* 扫码授权面板 */}
      {qr && (
        <QrPanel
          key={`${qr.platform}:${qr.ticket || "starting"}`}
          session={qr}
          onClose={closeQr}
          onSuccess={handleQrSuccess}
        />
      )}

      {/* 已绑定账号 */}
      <div className="glass p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">已绑定账号（{list.length}）</h2>
          <span className="text-xs text-text-3">
            登录凭据加密存储 · 会话安全托管
          </span>
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
                <tr
                  key={a.id}
                  className="border-b border-stroke/50 last:border-0"
                >
                  <td className="py-2.5 pr-3">
                    <span className="chip text-[11px]">
                      <PlatformIcon platform={a.platform} size={14} />{" "}
                      {a.platformName}
                    </span>
                  </td>
                  <td className="py-2.5 pr-3 font-medium">
                    {editingId === a.id ? (
                      <input
                        autoFocus
                        defaultValue={a.nickname}
                        disabled={busyId === a.id}
                        maxLength={30}
                        className="w-36 rounded-lg border border-brand bg-transparent px-2 py-0.5 text-sm text-text-1 outline-none"
                        onKeyDown={(e) => {
                          if (e.key === "Enter")
                            void saveRename(
                              a.id,
                              (e.target as HTMLInputElement).value,
                            );
                          if (e.key === "Escape") setEditingId("");
                        }}
                        onBlur={(e) => void saveRename(a.id, e.target.value)}
                      />
                    ) : (
                      <span className="group inline-flex items-center gap-1.5">
                        {a.nickname}
                        <button
                          className="text-xs text-text-3 opacity-0 transition-opacity hover:text-brand group-hover:opacity-100"
                          title="重命名账号（用于多账号辨识）"
                          onClick={() => setEditingId(a.id)}
                        >
                          <PenLine className="h-3 w-3" />
                        </button>
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 pr-3">
                    {!capabilities?.find((item) => item.platform === a.platform)
                      ?.automaticEnabled ? (
                      <span className="chip border-warning/40 text-[11px] text-warning">
                        仅导出
                      </span>
                    ) : a.status === "active" ? (
                      <span className="chip border-success/40 text-[11px] text-success">
                        正常
                      </span>
                    ) : (
                      <span className="chip border-danger/40 text-[11px] text-danger">
                        已过期
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 pr-3 text-xs text-text-3">
                    {new Date(a.createdAt).toLocaleDateString("zh-CN")}
                  </td>
                  <td className="py-2.5">
                    <div className="flex gap-1.5">
                      {!capabilities?.find(
                        (item) => item.platform === a.platform,
                      )?.automaticEnabled ? null : a.status === "expired" ? (
                        <button
                          className="btn-primary px-2.5 py-0.5 text-xs"
                          disabled={busyId === a.id}
                          onClick={() => void reauth(a)}
                        >
                          重新授权
                        </button>
                      ) : (
                        <button
                          className="btn-ghost px-2.5 py-0.5 text-xs"
                          disabled={busyId === a.id}
                          onClick={() => void reauth(a)}
                        >
                          续期
                        </button>
                      )}
                      <button
                        className="btn-ghost px-2.5 py-0.5 text-xs"
                        disabled={busyId === a.id}
                        onClick={() => void unbind(a)}
                      >
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
          <div className="grid grid-cols-3 gap-2.5">
            {PUBLISH_PLATFORMS.map((p) => {
              const capability = capabilities?.find(
                (item) => item.platform === p,
              );
              return (
                <button
                  key={p}
                  className="btn-ghost justify-center"
                  disabled={!capability?.automaticEnabled}
                  title={capability?.reason}
                  onClick={() => void startBind(p)}
                >
                  <PlatformIcon platform={p} size={16} /> {PLATFORM_NAMES[p]}
                  {!capability?.automaticEnabled && " · 仅导出"}
                </button>
              );
            })}
          </div>
          <div className="mt-4 flex items-start gap-1.5 rounded-xl border border-info/30 bg-info/10 p-3 text-xs text-info">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              只有真实账号验收通过的平台开放扫码绑定；未验收平台仅生成完整人工发布包。
              Cookie 仅保存在您的账户中并加密存储，可随时解绑清除。
            </span>
          </div>
        </div>

        {/* 巡检设置 */}
        <div className="glass p-5">
          <h2 className="mb-4 font-medium">登录态巡检</h2>
          <div className="space-y-2.5 text-sm">
            <div className="flex items-center justify-between">
              <span>自动巡检频率</span>
              <span className="chip border-success/40 text-[11px] text-success">
                按系统配置
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span>失效后提醒</span>
              <span className="chip border-success/40 text-[11px] text-success">
                站内信 + 实时通知
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span>过期自动暂停发布</span>
              <span className="chip border-success/40 text-[11px] text-success">
                已开启
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span>解绑后保留历史数据</span>
              <span className="chip text-[11px]">保留 90 天</span>
            </div>
          </div>
        </div>
      </div>

      {/* 私信监听面板（仅抖音账号） */}
      {IM_ENABLED && <ImListenerPanel accounts={list} />}
    </div>
  );
}

/** 私信监听状态面板：展示抖音账号的 IM 监听状态 + 启停控制 */
function ImListenerPanel({ accounts }: { accounts: PublishAccount[] }) {
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState("");
  const [consentId, setConsentId] = useState("");
  const [riskAccepted, setRiskAccepted] = useState(false);
  const dyAccounts = accounts.filter((a) => a.platform === "douyin");

  const { data: listeners } = useQuery({
    queryKey: ["im-listener-status"],
    queryFn: () => imApi.listenerStatus(),
    refetchInterval: 15_000,
  });
  const { data: automationStatuses } = useQuery({
    queryKey: ["im-automation-status"],
    queryFn: () => imApi.automationStatus(),
  });

  const listenerMap = new Map<string, IMListenerStatus>();
  (listeners ?? []).forEach((l) => listenerMap.set(l.accountId, l));
  const automationMap = new Map<string, IMAutomationStatus>();
  (automationStatuses ?? []).forEach((item) =>
    automationMap.set(item.accountId, item),
  );

  const toggle = async (account: PublishAccount) => {
    const ls = listenerMap.get(account.id);
    const isListening = ls?.status === "listening";
    setBusyId(account.id);
    try {
      if (isListening) {
        await imApi.stopListener(account.id);
      } else {
        await imApi.startListener(account.id);
      }
      await queryClient.invalidateQueries({ queryKey: ["im-listener-status"] });
    } finally {
      setBusyId("");
    }
  };

  const enableAutomation = async (accountId: string) => {
    if (!riskAccepted) return;
    setBusyId(accountId);
    try {
      await imApi.authorizeAutomation(accountId);
      setConsentId("");
      setRiskAccepted(false);
      await queryClient.invalidateQueries({
        queryKey: ["im-automation-status"],
      });
    } finally {
      setBusyId("");
    }
  };

  const disableAutomation = async (accountId: string) => {
    setBusyId(accountId);
    try {
      await imApi.disableAutomation(accountId);
      await queryClient.invalidateQueries({
        queryKey: ["im-automation-status"],
      });
    } finally {
      setBusyId("");
    }
  };

  if (dyAccounts.length === 0) return null;

  return (
    <div className="glass p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-medium">私信监听（抖音 IM）</h2>
        <span className="text-xs text-text-3">
          WebSocket 长连接 · 实时收取私信
        </span>
      </div>
      <div className="space-y-2.5">
        {dyAccounts.map((a) => {
          const ls = listenerMap.get(a.id);
          const st = ls?.status ?? "disconnected";
          const automationAuthorized =
            automationMap.get(a.id)?.authorized ?? false;
          return (
            <div
              key={a.id}
              className="rounded-xl border border-stroke/60 px-4 py-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <PlatformIcon platform="douyin" size={18} />
                  <div>
                    <span className="text-sm font-medium">{a.nickname}</span>
                    <span className="ml-2 text-xs text-text-3">
                      {st === "listening" &&
                        `监听中${ls?.startedAt ? ` · ${new Date(ls.startedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} 启动` : ""}`}
                      {st === "disconnected" && "未连接"}
                      {st === "error" && `异常：${ls?.errorMsg || "未知"}`}
                    </span>
                    <p className="mt-1 text-xs text-text-3">
                      自动回复：
                      {automationAuthorized ? "已授权" : "未授权（仅生成建议）"}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {automationAuthorized ? (
                    <button
                      className="rounded-lg border border-danger/40 px-3 py-1 text-xs text-danger hover:bg-danger/10"
                      disabled={busyId === a.id}
                      onClick={() => void disableAutomation(a.id)}
                    >
                      紧急停止自动回复
                    </button>
                  ) : (
                    <button
                      className="btn-ghost px-3 py-1 text-xs"
                      disabled={busyId === a.id}
                      onClick={() => {
                        setConsentId(a.id);
                        setRiskAccepted(false);
                      }}
                    >
                      授权自动回复
                    </button>
                  )}
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${
                      st === "listening"
                        ? "bg-success animate-pulse"
                        : st === "error"
                          ? "bg-danger"
                          : "bg-text-3/40"
                    }`}
                  />
                  <button
                    className={`px-3 py-1 text-xs rounded-lg border transition-colors ${
                      st === "listening"
                        ? "border-danger/40 text-danger hover:bg-danger/10"
                        : "border-success/40 text-success hover:bg-success/10"
                    }`}
                    disabled={busyId === a.id || a.status !== "active"}
                    onClick={() => void toggle(a)}
                  >
                    {busyId === a.id
                      ? "…"
                      : st === "listening"
                        ? "停止监听"
                        : "启动监听"}
                  </button>
                </div>
              </div>
              {consentId === a.id && !automationAuthorized && (
                <div className="mt-3 rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-text-2">
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={riskAccepted}
                      onChange={(event) =>
                        setRiskAccepted(event.target.checked)
                      }
                    />
                    <span>
                      我确认已取得该账号的运营授权，并知悉自动回复可能触发平台风控；高风险内容仍只会生成建议。
                    </span>
                  </label>
                  <div className="mt-3 flex justify-end gap-2">
                    <button
                      className="btn-ghost px-3 py-1"
                      onClick={() => {
                        setConsentId("");
                        setRiskAccepted(false);
                      }}
                    >
                      取消
                    </button>
                    <button
                      className="btn-primary px-3 py-1"
                      disabled={!riskAccepted || busyId === a.id}
                      onClick={() => void enableAutomation(a.id)}
                    >
                      确认并启用
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex items-start gap-1.5 rounded-xl border border-info/30 bg-info/10 p-3 text-xs text-info">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          启动监听后，系统将实时接收该账号的抖音私信，可在「私信中心」查看和回复。
        </span>
      </div>
    </div>
  );
}
