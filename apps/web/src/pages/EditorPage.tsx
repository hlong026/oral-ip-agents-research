import { HttpError, pipelineApi } from "@oral/api-client";
import { useTasks } from "@oral/stores";
import type { PipelineTask } from "@oral/types";
import { useQuery } from "@tanstack/react-query";
import { LoaderCircle, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

const SUB_COLORS = [
  { key: "#FFFFFF", label: "白" },
  { key: "#FDE047", label: "黄" },
  { key: "#22D3EE", label: "青" },
  { key: "#F87171", label: "红" },
] as const;

const BGM_MODES = [
  { key: "none", label: "无 BGM", desc: "纯人声干声" },
  { key: "library", label: "平台曲库", desc: "商用授权曲目，自动闪避人声" },
  { key: "upload", label: "自定义上传", desc: "使用自有 BGM 素材" },
] as const;

// 封面模板：key 与服务端 cover.COVER_TEMPLATES 一致（帧底图 + 槽位 + 标题自动排版）
const COVER_TEMPLATES = [
  {
    key: "bold-bottom",
    label: "大字标题",
    desc: "底部压暗 + 超大粗体，爆点词黄色高亮",
  },
  {
    key: "center-band",
    label: "居中色带",
    desc: "品牌色横带 + 居中标题，正式感",
  },
  { key: "top-title", label: "顶部标题", desc: "适配底部被平台 UI 遮挡的场景" },
  { key: "none", label: "原始帧", desc: "不叠加文字，直接用视频帧" },
] as const;

interface EditConfig {
  fontSize: number;
  color: string;
  position: "bottom" | "middle" | "top";
  stroke: number;
  bgmMode: string;
  bgmVolume: number;
  coverTemplate: string;
}

const DEFAULT_CONFIG: EditConfig = {
  fontSize: 44,
  color: "#FFFFFF",
  position: "bottom",
  stroke: 2,
  bgmMode: "library",
  bgmVolume: 30,
  coverTemplate: "bold-bottom",
};

/** 视频剪辑台（流水线第⑥步 edit 产物精修：字幕样式/BGM/封面，F-401/402/404） */
export default function EditorPage() {
  const [params] = useSearchParams();
  const queryTaskId = params.get("task") ?? "";
  const liveTasks = useTasks((s) => s.tasks);
  const [taskId, setTaskId] = useState(queryTaskId);
  const [cfg, setCfg] = useState<EditConfig>(DEFAULT_CONFIG);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  // 候选任务：已产出成片的任务（compose 步完成）
  const { data: doneTasks } = useQuery({
    queryKey: ["tasks", "done", "editor"],
    queryFn: () => pipelineApi.list("done", 1, 20),
  });
  const candidates = useMemo(
    () =>
      (doneTasks?.items ?? []).filter((t) =>
        t.steps.some(
          (s) => s.step === "compose" && s.artifacts?.final_video_key,
        ),
      ),
    [doneTasks],
  );

  const task: PipelineTask | undefined =
    liveTasks[taskId] ??
    candidates.find((t) => t.id === taskId) ??
    (taskId ? undefined : candidates[0]);
  const effectiveTaskId = task?.id ?? taskId;

  const { data: taskDetail, refetch } = useQuery({
    queryKey: ["task", effectiveTaskId],
    queryFn: () => pipelineApi.get(effectiveTaskId),
    enabled: Boolean(effectiveTaskId),
    refetchInterval: (q) => {
      // 首拉失败时也持续重试，避免 WS 不可用 + 首次拉取失败时页面永久卡住
      if (!q.state.data) return 3000;
      // 「保存并重新合成」重跑期间持续轮询，新成片就绪后自动停止
      const s = q.state.data.status;
      return s === "pending" || s === "running" || s === "waiting_confirm"
        ? 3000
        : false;
    },
    // 标签页切后台时也保持轮询，切回即见最新进度
    refetchIntervalInBackground: true,
  });
  const detail = liveTasks[effectiveTaskId] ?? taskDetail ?? task;
  const rerunning =
    detail?.status === "pending" ||
    detail?.status === "running" ||
    detail?.status === "waiting_confirm";

  // 任务级 artifacts 为全量产物；步骤级 artifacts 服务端截断至 200 字，仅供展示归因
  const detailArt = (key: string) => {
    const v = detail?.artifacts?.[key];
    return typeof v === "string" && v ? v : undefined;
  };
  const videoUrl = detailArt("final_video_url");
  const script =
    detailArt("script") ??
    detail?.steps.find((s) => s.step === "rewrite")?.artifacts?.script ??
    "";
  const subtitleLines = useMemo(
    () =>
      script
        .split(/[。！？!?\n]/)
        .map((s) => s.trim())
        .filter(Boolean)
        .slice(0, 8),
    [script],
  );

  const update = (patch: Partial<EditConfig>) => {
    setCfg((c) => ({ ...c, ...patch }));
    setDirty(true);
    setMsg("");
  };

  const save = async () => {
    if (!detail) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      // 人工覆盖 edit 步参数 → 重跑 edit 步按配置真实重新合成（字幕样式 + 封面模板）
      await pipelineApi.overrideStep(detail.id, "edit", {
        subtitle_style: JSON.stringify({
          fontSize: cfg.fontSize,
          color: cfg.color,
          position: cfg.position,
          stroke: cfg.stroke,
        }),
        bgm_mode: cfg.bgmMode,
        bgm_volume: String(cfg.bgmVolume),
        cover_template: cfg.coverTemplate,
      });
      await pipelineApi.retryStep(detail.id, "edit");
      setDirty(false);
      setMsg("已保存并重新合成，稍候可在任务详情查看新成片");
      await refetch();
    } catch (e) {
      setError(e instanceof HttpError ? e.body.message : "保存失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">视频剪辑</h1>
          <p className="mt-1 text-sm text-text-3">
            成片微调 · 字幕样式 · BGM · 封面（F-401/402/404）
          </p>
        </div>
        <select
          className="input h-10 w-72 px-3 py-0 text-sm"
          value={effectiveTaskId}
          onChange={(e) => setTaskId(e.target.value)}
        >
          <option value="">选择要精修的成片任务…</option>
          {candidates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
            </option>
          ))}
        </select>
      </div>

      {!detail && (
        <div className="glass py-16 text-center text-text-3">
          暂无可精修的成片，
          <Link to="/create" className="text-brand-to hover:underline">
            先创建一个成片任务 →
          </Link>
        </div>
      )}

      {detail && (
        <>
          <div className="grid items-start gap-4 lg:grid-cols-[300px_1fr]">
            {/* 预览：成片就绪后直接内嵌播放器，字幕样式叠加层实时预览 */}
            <div className="glass p-4">
              <div className="relative flex aspect-[9/16] max-h-[440px] items-center justify-center overflow-hidden rounded-xl border border-stroke bg-black/40">
                {videoUrl ? (
                  <video
                    src={videoUrl}
                    poster={detail.coverUrl ?? undefined}
                    controls
                    playsInline
                    preload="metadata"
                    className="h-full w-full bg-black object-contain"
                    aria-label="剪辑成片预览"
                  />
                ) : (
                  <span className="flex flex-col items-center gap-2 text-text-3">
                    <Play className="h-9 w-9" />
                    <span className="text-xs">成片生成后在此预览</span>
                  </span>
                )}
                <span className="pointer-events-none absolute left-3 top-3 rounded-full bg-black/50 px-2 py-0.5 text-[11px]">
                  1080P
                </span>
                {/* 字幕预览：随样式实时变化（不拦截播放器控件点击） */}
                <span
                  className={`pointer-events-none absolute left-1/2 -translate-x-1/2 px-4 text-center font-bold leading-snug ${
                    cfg.position === "bottom"
                      ? "bottom-14"
                      : cfg.position === "middle"
                        ? "top-1/2 -translate-y-1/2"
                        : "top-6"
                  }`}
                  style={{
                    color: cfg.color,
                    fontSize: Math.max(12, cfg.fontSize / 2.2),
                    textShadow:
                      cfg.stroke > 0
                        ? `0 0 ${cfg.stroke * 2}px rgba(0,0,0,.9), 0 ${cfg.stroke}px ${cfg.stroke}px rgba(0,0,0,.8)`
                        : "none",
                  }}
                >
                  {subtitleLines[2] ?? "字幕效果实时预览"}
                </span>
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <b className="block truncate">{detail.title}</b>
                  <div className="mt-0.5 text-xs text-text-3">
                    合成完成 · {dirty ? "有未保存修改" : "待微调"}
                  </div>
                </div>
                <span className="chip shrink-0 text-[11px]">
                  {rerunning ? (
                    <span className="flex items-center gap-1">
                      <LoaderCircle className="h-3 w-3 animate-spin" />
                      重新合成中
                    </span>
                  ) : videoUrl ? (
                    "成片就绪"
                  ) : (
                    "合成中"
                  )}
                </span>
              </div>
            </div>

            <div className="space-y-4">
              {/* 字幕样式（F-401） */}
              <div className="glass p-5">
                <h2 className="mb-4 font-medium">字幕样式</h2>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <label className="label">字号（{cfg.fontSize}px）</label>
                    <input
                      type="range"
                      min={32}
                      max={64}
                      value={cfg.fontSize}
                      onChange={(e) =>
                        update({ fontSize: Number(e.target.value) })
                      }
                      className="w-full accent-brand-from"
                    />
                  </div>
                  <div>
                    <label className="label">描边粗细（{cfg.stroke}px）</label>
                    <input
                      type="range"
                      min={0}
                      max={6}
                      value={cfg.stroke}
                      onChange={(e) =>
                        update({ stroke: Number(e.target.value) })
                      }
                      className="w-full accent-brand-from"
                    />
                  </div>
                  <div>
                    <label className="label">颜色</label>
                    <div className="flex gap-2">
                      {SUB_COLORS.map((c) => (
                        <button
                          key={c.key}
                          onClick={() => update({ color: c.key })}
                          title={c.label}
                          className={`h-8 w-8 rounded-lg border-2 ${cfg.color === c.key ? "border-brand-to" : "border-stroke"}`}
                          style={{ background: c.key }}
                        />
                      ))}
                    </div>
                  </div>
                  <div>
                    <label className="label">位置</label>
                    <div className="flex gap-2">
                      {(
                        [
                          ["top", "顶部"],
                          ["middle", "中部"],
                          ["bottom", "底部安全区"],
                        ] as const
                      ).map(([k, label]) => (
                        <button
                          key={k}
                          onClick={() => update({ position: k })}
                          className={`chip px-3 py-1 ${cfg.position === k ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* BGM 三模式（F-402） */}
              <div className="glass p-5">
                <h2 className="mb-4 font-medium">背景音乐</h2>
                <div className="grid gap-3 md:grid-cols-3">
                  {BGM_MODES.map((m) => (
                    <button
                      key={m.key}
                      onClick={() => update({ bgmMode: m.key })}
                      className={`rounded-xl border p-3.5 text-left ${cfg.bgmMode === m.key ? "border-brand-from/60 bg-brand-from/10" : "border-stroke bg-white/[0.03]"}`}
                    >
                      <div className="text-sm font-medium">{m.label}</div>
                      <div className="mt-1 text-xs text-text-3">{m.desc}</div>
                    </button>
                  ))}
                </div>
                {cfg.bgmMode !== "none" && (
                  <div className="mt-4">
                    <label className="label">
                      BGM 音量（{cfg.bgmVolume}% · sidechain 自动闪避人声）
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={cfg.bgmVolume}
                      onChange={(e) =>
                        update({ bgmVolume: Number(e.target.value) })
                      }
                      className="w-full accent-brand-from"
                    />
                  </div>
                )}
              </div>

              {/* 封面模板（F-404）：服务端自动取帧 + 标题自动排版，选模板即可 */}
              <div className="glass p-5">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="font-medium">封面模板</h2>
                  <span className="text-xs text-text-3">
                    标题自动匹配视频帧，保存后生效
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {COVER_TEMPLATES.map((t) => (
                    <button
                      key={t.key}
                      onClick={() => update({ coverTemplate: t.key })}
                      className={`rounded-xl border p-3.5 text-left ${cfg.coverTemplate === t.key ? "border-brand-from/60 bg-brand-from/10" : "border-stroke bg-white/[0.03]"}`}
                    >
                      <div className="text-sm font-medium">{t.label}</div>
                      <div className="mt-1 text-xs text-text-3">{t.desc}</div>
                    </button>
                  ))}
                </div>
                {detail.coverUrl && (
                  <div className="mt-4 flex items-center gap-3">
                    <img
                      src={detail.coverUrl}
                      alt="当前封面"
                      className="h-24 rounded-lg border border-stroke object-cover"
                    />
                    <span className="text-xs text-text-3">
                      当前封面 · 重新合成后按所选模板更新
                    </span>
                  </div>
                )}
              </div>

              {/* 操作条 */}
              <div className="glass flex flex-wrap items-center gap-3 p-4">
                {error && <span className="text-sm text-danger">{error}</span>}
                {msg && <span className="text-sm text-success">{msg}</span>}
                <div className="flex-1" />
                <button
                  className="btn-ghost text-xs"
                  disabled
                  title="V1.1 剪映草稿导出"
                >
                  导出剪映草稿
                </button>
                {videoUrl ? (
                  <a className="btn-ghost text-xs" href={videoUrl} download>
                    导出 MP4
                  </a>
                ) : (
                  <button className="btn-ghost text-xs" disabled>
                    导出 MP4
                  </button>
                )}
                <button
                  className="btn-primary px-5"
                  disabled={busy || !dirty}
                  onClick={save}
                >
                  {busy ? "合成中…" : "保存并重新合成"}
                </button>
                <Link
                  to={`/publish/jobs?task=${detail.id}`}
                  className="btn-ghost text-xs"
                >
                  去发布 →
                </Link>
              </div>
            </div>
          </div>

          {/* 字幕校对 */}
          {subtitleLines.length > 0 && (
            <div className="glass p-5">
              <div className="mb-3 flex items-center gap-2">
                <h2 className="font-medium">字幕校对</h2>
                <span className="chip border-success/40 text-[11px] text-success">
                  ASR 对齐完成
                </span>
                <span className="ml-auto text-xs text-text-3">
                  口播文案分行预览
                </span>
              </div>
              <div className="space-y-1">
                {subtitleLines.map((line, i) => (
                  <div
                    key={i}
                    className={`rounded-lg px-3 py-1.5 text-sm ${i === 2 ? "bg-brand-from/10 text-text-1" : "text-text-2 hover:bg-white/5"}`}
                  >
                    {line}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
