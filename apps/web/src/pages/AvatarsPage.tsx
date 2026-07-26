import { HttpError, avatarApi, personaApi } from "@oral/api-client";
import { useIp } from "@oral/stores";
import type { Avatar, Persona } from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Play, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import AssetNav from "../components/AssetNav";
import {
  confirmMeteredOperation,
  mediaDurationSeconds,
} from "../lib/meteredOperation";

// 供应商数字人训练素材约束：mp4/mov（h264），≤500MB；产品侧收紧为 30 秒～3 分钟
const VIDEO_MAX_BYTES = 500 * 1024 * 1024;
const VIDEO_MIN_SECONDS = 30;
const VIDEO_MAX_SECONDS = 180;

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
            <X className="h-3.5 w-3.5" />
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
            <span className="text-text-3">
              <Bot className="h-8 w-8" />
            </span>
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
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-black/55 pl-0.5 text-white shadow-lg backdrop-blur-sm transition-transform hover:scale-110">
                <Play className="h-4 w-4" />
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

/** 训练新分身表单（合规红线：强制 consent 授权勾选） */
function TrainForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [scene, setScene] = useState("口播");
  const [consent, setConsent] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = async () => {
    if (!file || !consent || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      // 提交前兼容校验：格式/大小/时长不达标时直接拦截，避免白扣积分
      if (!/\.(mp4|mov)$/i.test(file.name))
        throw new Error("训练视频仅支持 MP4/MOV（H264 编码）");
      if (file.size > VIDEO_MAX_BYTES)
        throw new Error("训练视频超过 500MB，请压缩后重试");
      const consentToken = `consent-${Date.now()}`;
      const seconds = await mediaDurationSeconds(file);
      if (seconds < VIDEO_MIN_SECONDS || seconds > VIDEO_MAX_SECONDS)
        throw new Error("训练视频时长需在 30 秒～3 分钟之间");
      const quoteId = await confirmMeteredOperation(
        "digital_human",
        "数字分身训练",
        {
          seconds,
          assets: 1,
        },
      );
      if (!quoteId) return;
      await avatarApi.clone(
        `${name.trim()} · ${scene}`,
        consentToken,
        file,
        quoteId,
      );
      setName("");
      setFile(null);
      setConsent(false);
      onDone();
    } catch (e) {
      setError(
        e instanceof HttpError
          ? e.body.message
          : e instanceof Error && e.message
            ? e.message
            : "训练任务创建失败，请重试",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="glass-strong space-y-3 p-5">
      <h2 className="font-medium">训练一个新的数字分身</h2>
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
          训练素材（30s–3min 正面口播视频，1080P，MP4/MOV）
        </label>
        <button
          className="btn-ghost flex w-full items-center justify-center gap-1.5 border-dashed py-6 text-text-3"
          onClick={() => fileRef.current?.click()}
        >
          {file ? (
            `已选择：${file.name}`
          ) : (
            <>
              <Upload className="h-4 w-4" /> 点击选择视频文件（MP4/MOV）
            </>
          )}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="video/*,.mp4,.mov"
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
        <span>我确认拥有该形象的合法授权</span>
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
        {busy ? "训练任务创建中…" : "开始训练"}
      </button>
    </div>
  );
}

/** 数字人中心（F-301~F-304：形象克隆/状态轮询/绑定 IP） */
export default function AvatarsPage() {
  const queryClient = useQueryClient();
  const { current, personas, load } = useIp();

  const { data: avatars, refetch } = useQuery({
    queryKey: ["avatars"],
    queryFn: async () => {
      const listed = await avatarApi.list();
      // 训练中的分身需要显式查询 status 接口，后端在该接口内轮询供应商并推进状态
      const updates = await Promise.all(
        listed
          .filter((a) => a.status === "training")
          .map((a) => avatarApi.status(a.id)),
      );
      const byId = new Map(updates.map((a) => [a.id, a.status]));
      return listed.map((a) => ({
        ...a,
        status: byId.get(a.id) ?? a.status,
      }));
    },
    refetchInterval: (q) =>
      (q.state.data ?? []).some((a) => a.status === "training") ? 8000 : false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["avatars"] });
    await refetch();
  };

  const list = avatars ?? [];
  const mine = list.filter((a) => a.source === "clone");
  const boundAvatar = list.find((a) => a.id === current?.avatarId);
  const ipOf = (a: Avatar) => personas.find((p) => p.avatarId === a.id);

  const bindToCurrent = async (a: Avatar) => {
    if (!current) return;
    await personaApi.update(current.id, { avatarId: a.id });
    await load();
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
                <span className="text-text-3">
                  <Bot className="h-12 w-12" />
                </span>
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

        {/* 右列：训练表单 */}
        <div className="space-y-4">
          <TrainForm onDone={() => void refresh()} />
        </div>
      </div>

      {/* 我的分身（通栏） */}
      <div className="glass p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">我的分身（{mine.length}）</h2>
          <span className="text-xs text-text-3">训练中每 8s 自动刷新</span>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
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
                        <span className="chip border-warning/40 text-[11px] text-warning">
                          训练中
                        </span>
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
                <div className="mt-2">
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
                  {a.status === "ready" && (
                    <Link
                      className="btn-ghost block w-full px-2.5 py-1 text-center text-xs text-brand-to"
                      to={`/create?avatarId=${a.id}`}
                    >
                      用 TA 去成片 →
                    </Link>
                  )}
                </div>
              </div>
            );
          })}
          {mine.length === 0 && (
            <div className="col-span-full py-8 text-center text-text-3">
              还没有训练分身，先在上方训练一个新的数字分身
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
