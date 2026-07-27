import { HttpError, pipelineApi } from "@oral/api-client";
import { useTasks } from "@oral/stores";
import type { EditConfig as ApiEditConfig, PipelineTask } from "@oral/types";
import { useQuery } from "@tanstack/react-query";
import { LoaderCircle, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { confirmMeteredOperation } from "../lib/meteredOperation";

const SUB_COLORS = [
  { key: "#FFFFFF", label: "白" },
  { key: "#FDE047", label: "黄" },
  { key: "#22D3EE", label: "青" },
  { key: "#F87171", label: "红" },
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
  bgmMode: "off";
  bgmVolume: 0;
  coverTemplate: ApiEditConfig["coverTemplate"];
}

const DEFAULT_CONFIG: EditConfig = {
  fontSize: 44,
  color: "#FFFFFF",
  position: "bottom",
  stroke: 2,
  bgmMode: "off",
  bgmVolume: 0,
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
  const [submittedRenderId, setSubmittedRenderId] = useState("");
  const idempotencyKey = useRef("");

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

  const { data: taskDetail } = useQuery({
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
  const { data: renderVersions, refetch: refetchRenders } = useQuery({
    queryKey: ["task-renders", effectiveTaskId],
    queryFn: () => pipelineApi.renderVersions(effectiveTaskId),
    enabled: Boolean(effectiveTaskId),
    refetchInterval: (query) =>
      query.state.data?.some((render) =>
        ["pending", "running", "rendered"].includes(render.status),
      )
        ? 3000
        : false,
    refetchIntervalInBackground: true,
  });
  const activeRender = renderVersions?.find((render) => render.isActive);
  const inflightRender = renderVersions?.find((render) =>
    ["pending", "running", "rendered"].includes(render.status),
  );
  const submittedRender = renderVersions?.find(
    (render) => render.id === submittedRenderId,
  );
  const terminalAttempt = renderVersions?.find(
    (render) =>
      !render.isActive &&
      ["failed", "canceled"].includes(render.status) &&
      render.version > (activeRender?.version ?? 0),
  );
  const rerunning =
    Boolean(inflightRender) ||
    detail?.status === "pending" ||
    detail?.status === "running" ||
    detail?.status === "waiting_confirm";

  useEffect(() => {
    setDirty(false);
    setMsg("");
    setError("");
    setSubmittedRenderId("");
    idempotencyKey.current = "";
  }, [effectiveTaskId]);

  useEffect(() => {
    if (!activeRender || dirty || submittedRenderId) return;
    setCfg({
      fontSize: activeRender.config.subtitleStyle.fontSize,
      color: activeRender.config.subtitleStyle.color,
      position: activeRender.config.subtitleStyle.position,
      stroke: activeRender.config.subtitleStyle.stroke,
      bgmMode: "off",
      bgmVolume: 0,
      coverTemplate: activeRender.config.coverTemplate,
    });
  }, [activeRender, dirty, submittedRenderId]);

  useEffect(() => {
    if (!terminalAttempt) return;
    setCfg({
      fontSize: terminalAttempt.config.subtitleStyle.fontSize,
      color: terminalAttempt.config.subtitleStyle.color,
      position: terminalAttempt.config.subtitleStyle.position,
      stroke: terminalAttempt.config.subtitleStyle.stroke,
      bgmMode: "off",
      bgmVolume: 0,
      coverTemplate: terminalAttempt.config.coverTemplate,
    });
    setDirty(true);
    setSubmittedRenderId("");
    idempotencyKey.current = "";
    setMsg("");
    setError(
      terminalAttempt.status === "failed"
        ? terminalAttempt.error || "重新合成失败，请稍后重试"
        : "本次重合成已取消，可调整后重新提交",
    );
  }, [terminalAttempt]);

  useEffect(() => {
    if (submittedRender?.status !== "done") return;
    setSubmittedRenderId("");
    idempotencyKey.current = "";
    setMsg(`v${submittedRender.version} 已完成并切换为当前成片`);
  }, [submittedRender]);

  // 任务级 artifacts 为全量产物；步骤级 artifacts 服务端截断至 200 字，仅供展示归因
  const detailArt = (key: string) => {
    const v = detail?.artifacts?.[key];
    return typeof v === "string" && v ? v : undefined;
  };
  const videoUrl = activeRender?.videoUrl ?? detailArt("final_video_url");
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
    idempotencyKey.current = "";
    setMsg("");
  };

  const save = async () => {
    if (!detail || !activeRender) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const quoteId = await confirmMeteredOperation(
        "hd_export",
        "重新合成成片",
        { assets: 1 },
      );
      idempotencyKey.current ||=
        globalThis.crypto?.randomUUID?.() ??
        `editor-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const config: ApiEditConfig = {
        subtitleStyle: {
          fontSize: cfg.fontSize,
          color: cfg.color,
          position: cfg.position,
          stroke: cfg.stroke,
        },
        bgmMode: "off",
        bgmVolume: 0,
        coverTemplate: cfg.coverTemplate,
      };
      const created = await pipelineApi.recompose(detail.id, {
        quoteId,
        idempotencyKey: idempotencyKey.current,
        baseVersion: activeRender.version,
        config,
      });
      setSubmittedRenderId(created.id);
      setDirty(false);
      setMsg(
        `已提交 v${activeRender.version + 1}，旧成片会保留到新版本通过质量检查`,
      );
      await refetchRenders();
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
            成片微调 · 字幕样式 · 封面 · 版本可追溯
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
                    当前 v{activeRender?.version ?? detail.activeRenderVersion}{" "}
                    · {dirty ? "有未保存修改" : "配置已同步"}
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

              {/* BGM 在真实素材归属链路开放前保持关闭，避免伪曲库与任意 key。 */}
              <div className="glass p-5">
                <h2 className="mb-4 font-medium">背景音乐</h2>
                <div className="rounded-xl border border-stroke bg-white/[0.03] p-3.5">
                  <div className="text-sm font-medium">当前使用纯人声</div>
                  <div className="mt-1 text-xs leading-relaxed text-text-3">
                    平台曲库和自定义上传将在素材库完成真实授权、归属校验与版权审计后开放；当前不会提交虚假的
                    BGM 配置。
                  </div>
                </div>
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
                {(activeRender?.coverUrl || detail.coverUrl) && (
                  <div className="mt-4 flex items-center gap-3">
                    <img
                      src={activeRender?.coverUrl ?? detail.coverUrl ?? ""}
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
                  disabled={busy || rerunning || !dirty || !activeRender}
                  onClick={save}
                >
                  {busy ? "合成中…" : "保存并重新合成"}
                </button>
                {inflightRender?.status === "pending" && (
                  <button
                    className="btn-ghost text-xs"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      setError("");
                      try {
                        await pipelineApi.cancelRender(
                          detail.id,
                          inflightRender.id,
                        );
                        setSubmittedRenderId("");
                        idempotencyKey.current = "";
                        setDirty(true);
                        setMsg(
                          "已取消本次重合成，当前成片保持不变，可再次提交",
                        );
                        await refetchRenders();
                      } catch (e) {
                        setError(
                          e instanceof HttpError
                            ? e.body.message
                            : "取消失败，请重试",
                        );
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    取消本次重合成
                  </button>
                )}
                {inflightRender?.status === "running" && (
                  <span className="text-xs text-text-3">
                    已开始合成，当前不可取消
                  </span>
                )}
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
