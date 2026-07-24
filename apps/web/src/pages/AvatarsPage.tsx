import { HttpError, avatarApi, personaApi } from "@oral/api-client";
import { useIp } from "@oral/stores";
import type { Avatar, Persona } from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import AssetNav from "../components/AssetNav";
import {
  confirmMeteredOperation,
  mediaDurationSeconds,
} from "../lib/meteredOperation";

/** 预览图 + 中央 ▶ 播放按钮：点击后卡内切换为视频播放，关闭返回封面 */
function PreviewThumb({
  avatar,
  className = "",
}: {
  avatar: Avatar;
  className?: string;
}) {
  const [playing, setPlaying] = useState(false);
  return (
    <div
      className={`relative flex aspect-[9/16] items-center justify-center overflow-hidden rounded-lg bg-gradient-to-b from-white/10 to-transparent ${className}`}
    >
      {playing && avatar.previewUrl ? (
        <>
          <video
            src={avatar.previewUrl}
            className="h-full w-full object-cover"
            autoPlay
            controls
            loop
          />
          <button
            aria-label="关闭预览"
            className="absolute right-1.5 top-1.5 z-10 flex h-6 w-6 items-center justify-center rounded-full bg-black/60 text-xs text-white hover:bg-black/80"
            onClick={(e) => {
              e.stopPropagation();
              setPlaying(false);
            }}
          >
            ✕
          </button>
        </>
      ) : (
        <>
          {avatar.coverUrl ? (
            <img
              src={avatar.coverUrl}
              alt={avatar.name}
              className="h-full w-full object-cover"
            />
          ) : (
            <span className="text-3xl">♟</span>
          )}
          {avatar.previewUrl && (
            <button
              aria-label={`预览 ${avatar.name}`}
              className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors hover:bg-black/25"
              onClick={(e) => {
                e.stopPropagation();
                setPlaying(true);
              }}
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-black/55 pl-0.5 text-base text-white shadow-lg backdrop-blur-sm transition-transform hover:scale-110">
                ▶
              </span>
            </button>
          )}
        </>
      )}
    </div>
  );
}

/** 绑定 IP 的小圆头像标识（分身卡右下角） */
function IpBadge({ ip }: { ip: Persona }) {
  return (
    <span
      title={`已绑定 IP：${ip.name}`}
      className="flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold text-white ring-2 ring-bg-1"
      style={{ background: ip.avatarGrad }}
    >
      {ip.avatarChar}
    </span>
  );
}

/** 训练新分身表单（合规红线：强制 consent 授权勾选）
 *  支持两种克隆方式：视频克隆（30s–3min 口播视频）/ 图片克隆（单张正面照）
 */
function TrainForm({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<"video" | "image">("video");
  const [name, setName] = useState("");
  const [scene, setScene] = useState("口播");
  const [consent, setConsent] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const switchMode = (m: "video" | "image") => {
    setMode(m);
    setFile(null);
    setError("");
    // 非受控 input：手动清空，否则重选同一文件不触发 onChange
    if (fileRef.current) fileRef.current.value = "";
  };

  const submit = async () => {
    if (!file || !consent || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const consentToken = `consent-${Date.now()}`;
      const fullName = `${name.trim()} · ${scene}`;
      if (mode === "video") {
        const seconds = await mediaDurationSeconds(file);
        const quoteId = await confirmMeteredOperation(
          "digital_human",
          "数字分身训练",
          { seconds, assets: 1 },
        );
        if (!quoteId) return;
        await avatarApi.clone(fullName, consentToken, file, quoteId);
      } else {
        // 图片克隆：后端按 {seconds:1, images:1, assets:1} 计量
        const quoteId = await confirmMeteredOperation(
          "digital_human",
          "图片分身克隆",
          { seconds: 1, images: 1, assets: 1 },
        );
        if (!quoteId) return;
        await avatarApi.cloneByImage(fullName, consentToken, file, quoteId);
      }
      setName("");
      setFile(null);
      setConsent(false);
      if (fileRef.current) fileRef.current.value = "";
      onDone();
    } catch (e) {
      setError(
        e instanceof HttpError ? e.body.message : "训练任务创建失败，请重试",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="glass-strong space-y-3 p-5">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">训练一个新的数字分身</h2>
        <span className="text-xs text-text-3">
          {mode === "video" ? "飞影 API · 约 2 小时" : "图片克隆 · 更快出片"}
        </span>
      </div>
      {/* 克隆方式 Tab */}
      <div className="flex gap-2">
        {(
          [
            { key: "video", label: "视频克隆" },
            { key: "image", label: "图片克隆" },
          ] as const
        ).map((t) => (
          <button
            key={t.key}
            onClick={() => switchMode(t.key)}
            className={`chip px-3 py-1.5 ${mode === t.key ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="label">分身名称</label>
          <input
            className="input"
            placeholder="例：李老师 · 休闲版"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label className="label">使用场景</label>
          <div className="flex gap-2">
            {["口播", "带货", "课程"].map((s) => (
              <button
                key={s}
                onClick={() => setScene(s)}
                className={`chip px-3 py-1.5 ${scene === s ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div>
        <label className="label">
          {mode === "video"
            ? "训练素材（30s–3min 正面口播视频，1080P，MP4/MOV）"
            : "训练素材（单张高清正面照，JPG/PNG，五官清晰无遮挡）"}
        </label>
        <button
          className="btn-ghost w-full border-dashed py-6 text-text-3"
          onClick={() => fileRef.current?.click()}
        >
          {file
            ? `已选择：${file.name}`
            : mode === "video"
              ? "⬆ 点击选择视频文件"
              : "⬆ 点击选择图片文件"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept={
            mode === "video" ? "video/*,.mp4,.mov" : "image/*,.jpg,.jpeg,.png"
          }
          className="hidden"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </div>
      <label className="flex cursor-pointer items-start gap-2 rounded-xl border border-info/30 bg-info/10 p-3 text-xs text-info">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
        />
        <span>
          我确认拥有该形象的合法授权（F-302 合规要求），授权凭证 consent_token
          将随训练任务一并存证。
        </span>
      </label>
      {error && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}
      <button
        className="btn-primary w-full"
        disabled={busy || !file || !consent || !name.trim()}
        onClick={submit}
      >
        {busy
          ? "训练任务创建中…"
          : mode === "video"
            ? "开始训练（约 2 小时）"
            : "开始图片克隆"}
      </button>
    </div>
  );
}

/** 训练中分身的进度徽标：独立轮询 status 端点，就绪/失败后刷新列表 */
function TrainingBadge({ avatarId }: { avatarId: string }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["avatar-status", avatarId],
    queryFn: () => avatarApi.status(avatarId),
    // 终态后停止轮询
    refetchInterval: (q) =>
      q.state.data?.status === "training" ? 4000 : false,
  });
  const status = data?.status;
  // 训练结束（ready/failed）后刷新分身列表（副作用放在 useEffect）
  useEffect(() => {
    if (status && status !== "training") {
      void queryClient.invalidateQueries({ queryKey: ["avatars"] });
    }
  }, [status, queryClient]);
  return (
    <span className="chip border-warning/40 text-[11px] text-warning">
      训练中 {data?.progress ?? 0}%
    </span>
  );
}

/** 数字人中心（F-301~F-304：形象克隆/公共库/状态轮询/绑定 IP） */
export default function AvatarsPage() {
  const queryClient = useQueryClient();
  const { current, personas, load } = useIp();

  const { data: avatars, refetch } = useQuery({
    queryKey: ["avatars"],
    queryFn: () => avatarApi.list(),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((a) => a.status === "training") ? 8000 : false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["avatars"] });
    await refetch();
  };

  const list = avatars ?? [];
  const mine = list.filter((a) => a.source === "clone");
  const publics = list.filter((a) => a.source === "public");
  const boundAvatar = list.find((a) => a.id === current?.avatarId);
  const ipOf = (a: Avatar) => personas.find((p) => p.avatarId === a.id);

  const bindToCurrent = async (a: Avatar) => {
    if (!current) return;
    await personaApi.update(current.id, { avatarId: a.id });
    await load();
  };

  const [actionId, setActionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");

  const handleDelete = async (a: Avatar) => {
    const isBound = current?.avatarId === a.id;
    const hint =
      a.status === "training"
        ? `确定删除分身「${a.name}」？训练中的分身将被取消，冻结额度自动退还。`
        : isBound
          ? `确定删除分身「${a.name}」？该分身是当前 IP 的默认分身，删除后需重新绑定。`
          : `确定删除分身「${a.name}」？此操作不可撤销。`;
    if (!window.confirm(hint)) return;
    setActionId(a.id);
    setActionError("");
    try {
      await avatarApi.delete(a.id);
      queryClient.setQueryData<Avatar[]>(["avatars"], (items = []) =>
        items.filter((item) => item.id !== a.id),
      );
      // 删除的是当前绑定分身时，同步 IP store 避免 avatarId 悬空
      if (isBound) await load();
    } catch (e) {
      setActionError(
        e instanceof HttpError ? e.body.message : "删除失败，请重试",
      );
    } finally {
      setActionId(null);
    }
  };

  return (
    <div className="space-y-5">
      <AssetNav />

      <div className="grid items-start gap-4 lg:grid-cols-[280px_1fr]">
        {/* 左列：当前默认分身预览 */}
        <div className="glass p-4">
          <div className="relative max-h-[420px] overflow-hidden rounded-xl border border-stroke">
            {boundAvatar ? (
              <PreviewThumb avatar={boundAvatar} />
            ) : (
              <div className="flex aspect-[9/16] items-center justify-center bg-gradient-to-b from-white/5 to-transparent">
                <span className="text-5xl">♟</span>
              </div>
            )}
            <span className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-black/50 px-3 py-1 text-xs">
              分身效果预览
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <div>
              <b>{boundAvatar?.name ?? "未绑定分身"}</b>
              <div className="mt-0.5 text-xs text-text-3">
                {boundAvatar
                  ? "默认分身"
                  : `为「${current?.name ?? "当前 IP"}」绑定`}
              </div>
            </div>
            {boundAvatar && (
              <span className="chip border-success/40 text-success">就绪</span>
            )}
          </div>
        </div>

        {/* 右列：训练表单 + 我的分身 */}
        <div className="space-y-4">
          <TrainForm onDone={() => void refresh()} />

          <div className="glass p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-medium">我的分身（{mine.length}）</h2>
              <span className="text-xs text-text-3">训练中每 8s 自动刷新</span>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {mine.map((a) => {
                const ip = ipOf(a);
                return (
                  <div
                    key={a.id}
                    className={`rounded-card border p-2.5 ${
                      current?.avatarId === a.id
                        ? "border-brand-from/60 bg-brand-from/10"
                        : "border-stroke bg-white/[0.03]"
                    }`}
                  >
                    <PreviewThumb avatar={a} />
                    <div className="mt-2 flex items-start justify-between gap-1.5">
                      <div className="min-w-0">
                        <div
                          className="truncate text-sm font-medium"
                          title={a.name}
                        >
                          {a.name}
                        </div>
                        <div className="mt-1 flex items-center gap-1.5">
                          {a.status === "ready" && (
                            <span className="chip border-success/40 text-[11px] text-success">
                              就绪
                            </span>
                          )}
                          {a.status === "training" && (
                            <TrainingBadge avatarId={a.id} />
                          )}
                          {a.status === "failed" && (
                            <span className="chip border-danger/40 text-[11px] text-danger">
                              失败
                            </span>
                          )}
                          {ip && <IpBadge ip={ip} />}
                        </div>
                      </div>
                    </div>
                    <div className="mt-2 space-y-1">
                      {a.status === "ready" &&
                        current &&
                        current.avatarId !== a.id && (
                          <button
                            className="btn-ghost w-full px-2.5 py-1 text-xs"
                            onClick={() => void bindToCurrent(a)}
                          >
                            设为默认
                          </button>
                        )}
                      {current?.avatarId === a.id && (
                        <div className="py-1 text-center text-xs text-success">
                          当前默认
                        </div>
                      )}
                      <button
                        className="btn-ghost w-full px-2.5 py-1 text-xs text-danger/70 hover:text-danger"
                        disabled={actionId === a.id}
                        onClick={() => void handleDelete(a)}
                      >
                        删除
                      </button>
                    </div>
                  </div>
                );
              })}
              {mine.length === 0 && (
                <div className="col-span-full py-8 text-center text-text-3">
                  还没有训练分身，也可先从下方公共形象库挑选
                </div>
              )}
              {actionError && (
                <div className="col-span-full text-sm text-danger">
                  {actionError}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 公共形象库（≥50 款，F-303） */}
      <div className="glass p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">公共形象库（{publics.length}）</h2>
          <span className="text-xs text-text-3">
            飞影公共库 · 点击卡片绑定到当前 IP
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          {publics.map((a) => (
            <div
              key={a.id}
              role="button"
              tabIndex={0}
              onClick={() => void bindToCurrent(a)}
              onKeyDown={(e) => e.key === "Enter" && void bindToCurrent(a)}
              className={`card-hover cursor-pointer rounded-card border p-2.5 text-left ${
                current?.avatarId === a.id
                  ? "border-brand-from/60 bg-brand-from/10"
                  : "border-stroke bg-white/[0.03]"
              }`}
            >
              <PreviewThumb avatar={a} />
              <div className="mt-2 truncate text-sm font-medium">{a.name}</div>
              <div className="mt-0.5 flex items-center justify-between text-xs text-text-3">
                <span>{a.style ?? "通用"}</span>
                {current?.avatarId === a.id && (
                  <span className="text-success">使用中</span>
                )}
              </div>
            </div>
          ))}
          {publics.length === 0 && (
            <div className="col-span-full py-8 text-center text-text-3">
              公共形象库加载中…
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
