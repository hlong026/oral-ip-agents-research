import { HttpError, pipelineApi } from "@oral/api-client";
import { useTasks } from "@oral/stores";
import type {
  CoverCandidate,
  MetadataSuggestionGroup,
  MetadataSuggestions,
  PipelineTask,
  PublicationContentSpec,
  PublicationRevision,
} from "@oral/types";
import { useQuery } from "@tanstack/react-query";
import { LoaderCircle, Play } from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { confirmMeteredOperation } from "../lib/meteredOperation";

const SUB_COLORS = [
  { key: "#FFFFFF", label: "白" },
  { key: "#FDE047", label: "黄" },
  { key: "#22D3EE", label: "青" },
  { key: "#F87171", label: "红" },
] as const;

const FONTS: PublicationContentSpec["subtitles"]["style"]["fontFamily"][] = [
  "Noto Sans CJK SC",
  "Source Han Sans SC",
  "PingFang SC",
];

const COVER_TEMPLATES = [
  { key: "bold-bottom", label: "大字标题" },
  { key: "center-band", label: "居中色带" },
  { key: "top-title", label: "顶部标题" },
  { key: "none", label: "原始帧" },
] as const;

function textArtifact(task: PipelineTask | undefined, key: string) {
  const value = task?.artifacts?.[key];
  return typeof value === "string" && value ? value : "";
}

function defaultContent(task: PipelineTask): PublicationContentSpec {
  const script = textArtifact(task, "script") || task.title;
  const lines = script
    .split(/[。！？!?\n]/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 8);

  return {
    schemaVersion: 1,
    title: task.title,
    topics: [],
    subtitles: {
      enabled: true,
      source: "asr_aligned",
      segments: (lines.length ? lines : [task.title]).map((text, index) => ({
        id: `segment-${index + 1}`,
        startMs: index * 1800,
        endMs: (index + 1) * 1800,
        text,
      })),
      style: {
        fontFamily: "PingFang SC",
        fontSize: 44,
        color: "#FFFFFF",
        stroke: 2,
        xPercent: 50,
        yPercent: 82,
      },
    },
    cover: { selectedFrameMs: 0, template: "bold-bottom", text: "" },
  };
}

function newIdempotencyKey() {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `publication-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

/** 成片发布定稿台：编辑 publication draft，定稿后交给发布页只读分发。 */
export default function EditorPage() {
  const [params] = useSearchParams();
  const queryTaskId = params.get("task") ?? "";
  const liveTasks = useTasks((s) => s.tasks);
  const taskId = queryTaskId;
  const [content, setContent] = useState<PublicationContentSpec | null>(null);
  const [draftRevision, setDraftRevision] = useState(0);
  const [currentRevision, setCurrentRevision] =
    useState<PublicationRevision | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [tagText, setTagText] = useState("");
  const [suggestions, setSuggestions] = useState<MetadataSuggestions | null>(
    null,
  );
  const [suggesting, setSuggesting] = useState(false);
  const [saveTick, setSaveTick] = useState(0);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const contentRef = useRef<PublicationContentSpec | null>(null);
  const revisionRef = useRef(0);
  const currentRevisionRef = useRef<PublicationRevision | null>(null);
  const contentVersionRef = useRef(0);
  const savedContentVersionRef = useRef(0);
  const savePromiseRef = useRef<Promise<PublicationRevision | null> | null>(
    null,
  );
  const overlayBoxRef = useRef<HTMLDivElement | null>(null);

  const { data: doneTasks } = useQuery({
    queryKey: ["tasks", "done", "editor"],
    queryFn: () => pipelineApi.list("done", 1, 20),
  });
  const candidates = useMemo(
    () =>
      (doneTasks?.items ?? []).filter((task) =>
        task.steps.some(
          (step) => step.step === "compose" && step.artifacts?.final_video_key,
        ),
      ),
    [doneTasks],
  );

  const task =
    liveTasks[taskId] ??
    candidates.find((item) => item.id === taskId) ??
    (taskId ? undefined : candidates[0]);
  const effectiveTaskId = task?.id ?? taskId;

  const { data: taskDetail } = useQuery({
    queryKey: ["task", effectiveTaskId],
    queryFn: () => pipelineApi.get(effectiveTaskId),
    enabled: Boolean(effectiveTaskId),
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  });
  const detail = liveTasks[effectiveTaskId] ?? taskDetail ?? task;

  const { data: draftData } = useQuery({
    queryKey: ["publication-draft", effectiveTaskId],
    queryFn: () => pipelineApi.publicationDraft(effectiveTaskId),
    enabled: Boolean(effectiveTaskId),
  });

  const {
    data: coverCandidates,
    error: coverError,
    isLoading: coverLoading,
  } = useQuery({
    queryKey: ["cover-candidates", effectiveTaskId],
    queryFn: () => pipelineApi.coverCandidates(effectiveTaskId),
    enabled: Boolean(effectiveTaskId),
    // 业务类错误（如缺少 clean 视频源的 409）不重试，直接把原因展示给用户
    retry: (failureCount, err) =>
      !(err instanceof HttpError && err.status < 500) && failureCount < 2,
  });

  const { data: revisions, refetch: refetchRevisions } = useQuery({
    queryKey: ["publication-revisions", effectiveTaskId],
    queryFn: () => pipelineApi.publicationRevisions(effectiveTaskId),
    enabled: Boolean(effectiveTaskId),
    refetchInterval: (query) =>
      query.state.data?.some((revision) => revision.status === "rendering")
        ? 3000
        : false,
    refetchIntervalInBackground: true,
  });

  const finalizedRevision = revisions?.find(
    (revision) =>
      revision.id === currentRevision?.id && revision.status === "finalized",
  );
  const isRendering =
    currentRevision?.status === "rendering" ||
    revisions?.some((revision) => revision.status === "rendering");

  useEffect(() => {
    setContent(null);
    setDraftRevision(0);
    setCurrentRevision(null);
    setDirty(false);
    setMsg("");
    setError("");
    setSuggestions(null);
    setTagText("");
    contentRef.current = null;
    revisionRef.current = 0;
    currentRevisionRef.current = null;
    contentVersionRef.current = 0;
    savedContentVersionRef.current = 0;
    savePromiseRef.current = null;
  }, [effectiveTaskId]);

  useEffect(() => {
    const nextContent =
      draftData?.content ?? (detail ? defaultContent(detail) : null);
    if (
      !nextContent ||
      dirty ||
      saving ||
      finalizing ||
      currentRevision?.status === "finalized" ||
      currentRevision?.status === "rendering" ||
      (draftData?.draftRevision ?? 0) < revisionRef.current
    ) {
      return;
    }
    setContent(nextContent);
    setDraftRevision(draftData?.draftRevision ?? 0);
    setCurrentRevision(draftData ?? null);
    contentRef.current = nextContent;
    revisionRef.current = draftData?.draftRevision ?? 0;
    currentRevisionRef.current = draftData ?? null;
    contentVersionRef.current = 0;
    savedContentVersionRef.current = 0;
  }, [detail, draftData, dirty, saving, finalizing, currentRevision?.status]);

  useEffect(() => {
    const refreshed = revisions?.find(
      (revision) => revision.id === currentRevisionRef.current?.id,
    );
    if (!refreshed) return;
    currentRevisionRef.current = refreshed;
    setCurrentRevision(refreshed);
    if (refreshed.status === "finalized") {
      setMsg("合成完成，标题/标签/封面/成片已就绪，可前往发布。");
      setError("");
    } else if (refreshed.status === "draft" && refreshed.lastError) {
      setMsg("");
      setError(refreshed.lastError);
    }
  }, [revisions]);

  useEffect(() => {
    if (!dirty || !effectiveTaskId || !content) return;
    const timer = window.setTimeout(() => {
      void saveNow();
    }, 700);
    return () => window.clearTimeout(timer);
    // saveTick makes explicit save requests reuse the same save path.
  }, [dirty, effectiveTaskId, content, saveTick]);

  const updateContent = (
    updater: (current: PublicationContentSpec) => PublicationContentSpec,
  ) => {
    const current = contentRef.current;
    if (!current) return;
    const next = updater(current);
    contentRef.current = next;
    contentVersionRef.current += 1;
    setContent(next);
    setDirty(true);
    setMsg("");
    setError("");
  };

  const saveNow = async () => {
    if (savePromiseRef.current) {
      await savePromiseRef.current;
    }
    if (
      savedContentVersionRef.current === contentVersionRef.current &&
      currentRevisionRef.current
    ) {
      return currentRevisionRef.current;
    }
    const draftContent = contentRef.current;
    if (!effectiveTaskId || !draftContent) return currentRevision;
    const snapshotVersion = contentVersionRef.current;
    setSaving(true);
    setError("");
    const pending = (async () => {
      try {
        const saved = await pipelineApi.savePublicationDraft(effectiveTaskId, {
          draftRevision: revisionRef.current,
          content: draftContent,
        });
        savedContentVersionRef.current = snapshotVersion;
        setDraftRevision(saved.draftRevision);
        revisionRef.current = saved.draftRevision;
        currentRevisionRef.current = saved;
        setCurrentRevision(saved);
        if (contentVersionRef.current === snapshotVersion) {
          setContent(saved.content);
          contentRef.current = saved.content;
          setDirty(false);
          setMsg("草稿已保存");
        } else {
          setDirty(true);
        }
        return saved;
      } catch (err) {
        setError(
          err instanceof HttpError ? err.body.message : "草稿保存失败，请重试",
        );
        throw err;
      } finally {
        setSaving(false);
      }
    })();
    savePromiseRef.current = pending;
    try {
      return await pending;
    } finally {
      if (savePromiseRef.current === pending) {
        savePromiseRef.current = null;
      }
    }
  };

  const toggleSection = (key: string) =>
    setCollapsed((current) => ({ ...current, [key]: !current[key] }));

  // 前端兜底清洗：去掉“第N组/标题：/序号”等前缀，防止 LLM 原文渗入输入框
  const cleanSuggestion = (value: string) =>
    value
      .replace(
        /^(第\s*\S+\s*组\s*[:：.、]?|标题\s*[:：]|标签\s*[:：]|封面\s*[:：]|\d+\s*[.、)]\s*)+/,
        "",
      )
      .trim();

  const applyGroup = (group: MetadataSuggestionGroup) => {
    const title = cleanSuggestion(group.title);
    const tags = group.tags
      .map((tag) => cleanSuggestion(tag).replace(/^#+/, ""))
      .filter(Boolean)
      .slice(0, 8);
    const coverText = cleanSuggestion(group.coverText ?? "").slice(0, 40);
    updateContent((current) => ({
      ...current,
      title: title || current.title,
      topics: tags.length ? tags : current.topics,
      cover: { ...current.cover, text: coverText || current.cover.text },
    }));
  };

  const requestSuggestions = async () => {
    if (!effectiveTaskId) return;
    setSuggesting(true);
    setError("");
    try {
      const next = await pipelineApi.metadataSuggestions(effectiveTaskId);
      setSuggestions(next);
      const first = next.groups?.[0] ?? {
        title: next.titles[0] ?? "",
        tags: next.tags,
        coverText: "",
      };
      if (first.title) {
        // 默认采用第 1 组：标题、标签、封面文字自动填充
        applyGroup(first);
        setMsg("已自动填充第 1 组建议，可在下方切换其他组");
      }
    } catch (err) {
      setError(
        err instanceof HttpError
          ? err.body.message
          : "AI生成失败，可继续手动填写",
      );
    } finally {
      setSuggesting(false);
    }
  };

  const addTag = (tag: string) => {
    const value = tag.trim();
    if (!value) return;
    updateContent((current) => ({
      ...current,
      topics: current.topics.includes(value)
        ? current.topics
        : [...current.topics, value].slice(0, 8),
    }));
    setTagText("");
  };

  const removeTag = (tag: string) => {
    updateContent((current) => ({
      ...current,
      topics: current.topics.filter((item) => item !== tag),
    }));
  };

  const startDrag = (event: ReactPointerEvent) => {
    event.preventDefault();
    const box = overlayBoxRef.current;
    if (!box) return;
    const move = (moveEvent: PointerEvent) => {
      const rect = box.getBoundingClientRect();
      const left = Number.isFinite(rect.left) ? rect.left : 0;
      const top = Number.isFinite(rect.top) ? rect.top : 0;
      const width = rect.width || Math.max(1, rect.right - rect.left);
      const height = rect.height || Math.max(1, rect.bottom - rect.top);
      if (width <= 0 || height <= 0) return;
      if (
        !Number.isFinite(moveEvent.clientX) ||
        !Number.isFinite(moveEvent.clientY)
      ) {
        return;
      }
      const xPercent = Math.round(
        Math.min(100, Math.max(0, ((moveEvent.clientX - left) / width) * 100)),
      );
      const yPercent = Math.round(
        Math.min(100, Math.max(0, ((moveEvent.clientY - top) / height) * 100)),
      );
      updateContent((current) => ({
        ...current,
        subtitles: {
          ...current.subtitles,
          style: { ...current.subtitles.style, xPercent, yPercent },
        },
      }));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  };

  const finalize = async () => {
    if (!effectiveTaskId || !contentRef.current) return;
    if (!contentRef.current.title.trim()) {
      setError("合成前请先填写标题");
      return;
    }
    setFinalizing(true);
    setError("");
    try {
      const saved = dirty ? await saveNow() : currentRevision;
      const quoteId = await confirmMeteredOperation(
        "hd_export",
        "合成最终视频",
        { assets: 1 },
      );
      const revision = await pipelineApi.finalizePublication(effectiveTaskId, {
        quoteId,
        idempotencyKey: newIdempotencyKey(),
        draftRevision: saved?.draftRevision ?? revisionRef.current,
      });
      setCurrentRevision(revision);
      currentRevisionRef.current = revision;
      setDraftRevision(revision.draftRevision);
      revisionRef.current = revision.draftRevision;
      setDirty(false);
      setMsg(
        revision.status === "finalized"
          ? "合成完成，可前往发布。"
          : "已提交合成，正在生成最终成片，完成后左侧预览自动更新。",
      );
      await refetchRevisions();
    } catch (err) {
      setError(
        err instanceof HttpError ? err.body.message : "定稿失败，草稿已保留",
      );
    } finally {
      setFinalizing(false);
    }
  };

  const videoUrl = textArtifact(detail, "final_video_url");
  const firstSubtitle =
    content?.subtitles.segments[0]?.text || "字幕效果实时预览";
  const firstThreeSeconds = (coverCandidates ?? []).filter(
    (candidate: CoverCandidate) => candidate.timestampMs <= 3000,
  );
  const suggestionGroups = useMemo<MetadataSuggestionGroup[]>(() => {
    if (!suggestions) return [];
    if (suggestions.groups?.length) return suggestions.groups.slice(0, 3);
    // 老版接口只有平铺 titles/tags 时降级拼组
    return suggestions.titles.slice(0, 3).map((title) => ({
      title,
      tags: suggestions.tags.slice(0, 6),
      coverText: "",
    }));
  }, [suggestions]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">视频剪辑</h1>
          <p className="mt-1 text-sm text-text-3">
            成片微调 · 字幕校对 · 封面 · 定稿发布
          </p>
        </div>
      </div>

      {!detail && (
        <div className="glass py-16 text-center text-text-3">
          暂无可精修的成片，
          <Link to="/create" className="text-brand-to hover:underline">
            先创建一个成片任务 →
          </Link>
        </div>
      )}

      {detail && content && (
        <>
          <div className="grid items-start gap-4 lg:grid-cols-[300px_1fr]">
            <div className="glass p-4">
              <div
                ref={overlayBoxRef}
                className="relative flex aspect-[9/16] max-h-[440px] items-center justify-center overflow-hidden rounded-xl border border-stroke bg-black/40"
              >
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
                {content.subtitles.enabled && (
                  <span
                    data-testid="subtitle-overlay"
                    onPointerDown={startDrag}
                    className="absolute cursor-move select-none px-4 text-center font-bold leading-snug"
                    style={{
                      left: `${content.subtitles.style.xPercent}%`,
                      top: `${content.subtitles.style.yPercent}%`,
                      transform: "translate(-50%, -50%)",
                      // 不换行才能保证 translate(-50%) 是真居中，贴边时不被容器挤压折行
                      whiteSpace: "nowrap",
                      color: content.subtitles.style.color,
                      fontFamily: content.subtitles.style.fontFamily,
                      fontSize: Math.max(
                        12,
                        content.subtitles.style.fontSize / 2.2,
                      ),
                      textShadow:
                        content.subtitles.style.stroke > 0
                          ? `0 0 ${content.subtitles.style.stroke * 2}px rgba(0,0,0,.9)`
                          : "none",
                    }}
                  >
                    {firstSubtitle}
                  </span>
                )}
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <b className="block truncate">{detail.title}</b>
                  <div className="mt-0.5 text-xs text-text-3">
                    draft r{draftRevision} ·{" "}
                    {saving ? "保存中" : dirty ? "有未保存修改" : "草稿已同步"}
                  </div>
                </div>
                <span className="chip shrink-0 text-[11px]">
                  {isRendering ? (
                    <span className="flex items-center gap-1">
                      <LoaderCircle className="h-3 w-3 animate-spin" />
                      成片合成中
                    </span>
                  ) : currentRevision?.status === "finalized" ? (
                    "已合成"
                  ) : (
                    "草稿"
                  )}
                </span>
              </div>
            </div>

            <div className="space-y-4">
              <div className="glass p-5">
                <div
                  className={`flex cursor-pointer select-none items-center justify-between gap-3 ${collapsed.meta ? "" : "mb-4"}`}
                  title="双击折叠/展开"
                  onDoubleClick={() => toggleSection("meta")}
                >
                  <h2 className="font-medium">标题和标签</h2>
                  <button
                    className="btn-ghost px-3 py-1 text-xs"
                    disabled={suggesting}
                    onClick={() => void requestSuggestions()}
                  >
                    {suggesting ? "生成中…" : "AI生成标题和标签"}
                  </button>
                </div>
                {!collapsed.meta && (
                  <>
                <label className="label" htmlFor="publication-title">
                  标题
                </label>
                <input
                  id="publication-title"
                  className="input"
                  value={content.title}
                  maxLength={128}
                  onChange={(event) =>
                    updateContent((current) => ({
                      ...current,
                      title: event.target.value,
                    }))
                  }
                />
                {suggestionGroups.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {suggestionGroups.map((group, index) => (
                      <div
                        key={`${group.title}-${index}`}
                        className="flex items-start justify-between gap-3 rounded-xl border border-stroke bg-white/[0.03] p-3"
                      >
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">
                            {group.title}
                          </div>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {group.tags.map((tag) => (
                              <span
                                key={tag}
                                className="chip px-2 py-0.5 text-[11px]"
                              >
                                #{tag}
                              </span>
                            ))}
                          </div>
                          {group.coverText && (
                            <div className="mt-1 text-xs text-text-3">
                              封面文字：{group.coverText}
                            </div>
                          )}
                        </div>
                        <button
                          className="btn-ghost shrink-0 px-3 py-1 text-xs"
                          onClick={() => applyGroup(group)}
                        >
                          采用第 {index + 1} 组
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {content.topics.map((tag) => (
                    <button
                      key={tag}
                      className="chip border-brand-to/40 px-2 py-1 text-xs text-brand-to"
                      onClick={() => removeTag(tag)}
                    >
                      #{tag} ×
                    </button>
                  ))}
                </div>
                <div className="mt-3 flex gap-2">
                  <input
                    className="input h-9 flex-1"
                    value={tagText}
                    onChange={(event) => setTagText(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") addTag(tagText);
                    }}
                    placeholder="手动添加标签"
                  />
                  <button
                    className="btn-ghost px-3 py-1 text-xs"
                    onClick={() => addTag(tagText)}
                  >
                    添加
                  </button>
                </div>
                  </>
                )}
              </div>

              <div className="glass p-5">
                <div
                  className={`flex cursor-pointer select-none items-center justify-between gap-3 ${collapsed.subtitles ? "" : "mb-4"}`}
                  title="双击折叠/展开"
                  onDoubleClick={() => toggleSection("subtitles")}
                >
                  <h2 className="font-medium">字幕</h2>
                  <button
                    role="switch"
                    aria-checked={content.subtitles.enabled}
                    onClick={() =>
                      updateContent((current) => ({
                        ...current,
                        subtitles: {
                          ...current.subtitles,
                          enabled: !current.subtitles.enabled,
                        },
                      }))
                    }
                    className={`chip px-3 py-1 text-xs ${
                      content.subtitles.enabled
                        ? "border-brand-from/50 bg-brand-from/15 text-text-1"
                        : ""
                    }`}
                  >
                    {content.subtitles.enabled ? "显示字幕" : "字幕已关闭"}
                  </button>
                </div>
                {!collapsed.subtitles && (
                  <>
                <fieldset
                  disabled={!content.subtitles.enabled}
                  className={`grid gap-4 md:grid-cols-2 ${
                    content.subtitles.enabled ? "" : "opacity-40"
                  }`}
                >
                  <div>
                    <label className="label" htmlFor="subtitle-font">
                      字幕字体
                    </label>
                    <select
                      id="subtitle-font"
                      className="input"
                      value={content.subtitles.style.fontFamily}
                      onChange={(event) =>
                        updateContent((current) => ({
                          ...current,
                          subtitles: {
                            ...current.subtitles,
                            style: {
                              ...current.subtitles.style,
                              fontFamily: event.target
                                .value as PublicationContentSpec["subtitles"]["style"]["fontFamily"],
                            },
                          },
                        }))
                      }
                    >
                      {FONTS.map((font) => (
                        <option key={font} value={font}>
                          {font}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="label">
                      字号（{content.subtitles.style.fontSize}px）
                    </label>
                    <input
                      type="range"
                      min={32}
                      max={64}
                      value={content.subtitles.style.fontSize}
                      onChange={(event) =>
                        updateContent((current) => ({
                          ...current,
                          subtitles: {
                            ...current.subtitles,
                            style: {
                              ...current.subtitles.style,
                              fontSize: Number(event.target.value),
                            },
                          },
                        }))
                      }
                      className="w-full accent-brand-from"
                    />
                  </div>
                  <div>
                    <label className="label">
                      描边粗细（{content.subtitles.style.stroke}px）
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={6}
                      value={content.subtitles.style.stroke}
                      onChange={(event) =>
                        updateContent((current) => ({
                          ...current,
                          subtitles: {
                            ...current.subtitles,
                            style: {
                              ...current.subtitles.style,
                              stroke: Number(event.target.value),
                            },
                          },
                        }))
                      }
                      className="w-full accent-brand-from"
                    />
                  </div>
                  <div>
                    <label className="label">颜色</label>
                    <div className="flex gap-2">
                      {SUB_COLORS.map((color) => (
                        <button
                          key={color.key}
                          title={color.label}
                          onClick={() =>
                            updateContent((current) => ({
                              ...current,
                              subtitles: {
                                ...current.subtitles,
                                style: {
                                  ...current.subtitles.style,
                                  color: color.key,
                                },
                              },
                            }))
                          }
                          className={`h-8 w-8 rounded-lg border-2 ${
                            content.subtitles.style.color === color.key
                              ? "border-brand-to"
                              : "border-stroke"
                          }`}
                          style={{ background: color.key }}
                        />
                      ))}
                    </div>
                  </div>
                </fieldset>
                <div className="mt-4 space-y-2">
                  {content.subtitles.segments.map((segment, index) => (
                    <div
                      key={segment.id}
                      className="grid gap-2 md:grid-cols-[90px_1fr]"
                    >
                      <span className="pt-2 text-xs text-text-3">
                        {(segment.startMs / 1000).toFixed(1)}s
                      </span>
                      <input
                        className="input"
                        value={segment.text}
                        aria-label={`字幕 ${index + 1}`}
                        onChange={(event) =>
                          updateContent((current) => ({
                            ...current,
                            subtitles: {
                              ...current.subtitles,
                              segments: current.subtitles.segments.map(
                                (item) =>
                                  item.id === segment.id
                                    ? { ...item, text: event.target.value }
                                    : item,
                              ),
                            },
                          }))
                        }
                      />
                    </div>
                  ))}
                </div>
                  </>
                )}
              </div>

              <div className="glass p-5">
                <div
                  className={`flex cursor-pointer select-none items-center justify-between ${collapsed.cover ? "" : "mb-4"}`}
                  title="双击折叠/展开"
                  onDoubleClick={() => toggleSection("cover")}
                >
                  <h2 className="font-medium">封面</h2>
                  <span className="text-xs text-text-3">
                    当前选中 {(content.cover.selectedFrameMs / 1000).toFixed(1)}
                    s
                  </span>
                </div>
                {!collapsed.cover && (
                  <>
                <div className="mb-4">
                  <label className="label" htmlFor="cover-text">
                    封面文字
                  </label>
                  <input
                    id="cover-text"
                    className="input"
                    maxLength={40}
                    value={content.cover.text ?? ""}
                    placeholder="12 字内爆点文案，可用【】标出 1 个爆点词"
                    onChange={(event) =>
                      updateContent((current) => ({
                        ...current,
                        cover: { ...current.cover, text: event.target.value },
                      }))
                    }
                  />
                  {content.cover.template === "none" && (
                    <p className="mt-1 text-xs text-text-3">
                      “原始帧”模板不叠加文字，切换其他模板后生效
                    </p>
                  )}
                </div>
                <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {COVER_TEMPLATES.map((template) => (
                    <button
                      key={template.key}
                      onClick={() =>
                        updateContent((current) => ({
                          ...current,
                          cover: { ...current.cover, template: template.key },
                        }))
                      }
                      className={`rounded-xl border p-3.5 text-left ${
                        content.cover.template === template.key
                          ? "border-brand-from/60 bg-brand-from/10"
                          : "border-stroke bg-white/[0.03]"
                      }`}
                    >
                      <div className="text-sm font-medium">
                        {template.label}
                      </div>
                    </button>
                  ))}
                </div>
                {coverError ? (
                  <p className="text-xs text-danger">
                    封面候选帧加载失败：
                    {coverError instanceof HttpError
                      ? coverError.body.message
                      : "网络异常，请稍后重试"}
                  </p>
                ) : firstThreeSeconds.length === 0 ? (
                  <p className="text-xs text-text-3">
                    {coverLoading ? "候选帧提取中…" : "暂无候选帧可选"}
                  </p>
                ) : (
                <div className="grid gap-3 sm:grid-cols-3">
                  {firstThreeSeconds.map((candidate) => (
                    <button
                      key={candidate.timestampMs}
                      className={`overflow-hidden rounded-xl border text-left ${
                        content.cover.selectedFrameMs === candidate.timestampMs
                          ? "border-brand-to"
                          : "border-stroke"
                      }`}
                      onClick={() =>
                        updateContent((current) => ({
                          ...current,
                          cover: {
                            ...current.cover,
                            selectedFrameMs: candidate.timestampMs,
                          },
                        }))
                      }
                    >
                      <img
                        src={candidate.imageUrl}
                        alt={`${(candidate.timestampMs / 1000).toFixed(1)}s 封面`}
                        className="aspect-video w-full bg-black object-cover"
                      />
                      <span className="block px-2 py-1 text-xs text-text-3">
                        选择 {(candidate.timestampMs / 1000).toFixed(1)}s 封面
                      </span>
                    </button>
                  ))}
                </div>
                )}
                  </>
                )}
              </div>

              <div className="glass flex flex-wrap items-center gap-3 p-4">
                {error && <span className="text-sm text-danger">{error}</span>}
                {msg && <span className="text-sm text-success">{msg}</span>}
                <div className="flex-1" />
                <button
                  className="btn-ghost text-xs"
                  disabled={saving || !dirty}
                  onClick={() => setSaveTick((value) => value + 1)}
                >
                  {saving ? "保存中…" : "保存草稿"}
                </button>
                <button
                  className="btn-primary px-5"
                  disabled={
                    saving ||
                    finalizing ||
                    isRendering ||
                    !content.title.trim() ||
                    (currentRevision?.status === "finalized" && !dirty)
                  }
                  onClick={() => void finalize()}
                >
                  {finalizing
                    ? "提交合成中…"
                    : isRendering
                      ? "成片合成中…"
                      : "合成最终视频"}
                </button>
                {currentRevision?.status === "finalized" && (
                  <Link
                    to={`/publish/jobs?task=${detail.id}&revision=${currentRevision.id}`}
                    className="btn-primary px-5 text-sm"
                  >
                    带内容去发布 →
                  </Link>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
