import {
  avatarApi,
  billingApi,
  catalogApi,
  contentApi,
  HttpError,
  pipelineApi,
  publishApi,
  voiceApi,
} from "@oral/api-client";
import { useIp, useQuota, useTasks } from "@oral/stores";
import {
  PLATFORM_NAMES,
  PUBLISH_PLATFORMS,
  type ModulePrice,
  type Platform,
  type PricePreview,
  type PricePreviewRequest,
  type RewriteIntensity,
} from "@oral/types";
import { useQuery } from "@tanstack/react-query";
import {
  ChartColumn,
  ChevronDown,
  ChevronUp,
  LoaderCircle,
  Music,
  Scissors,
  Smile,
  TriangleAlert,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import LinkSourceInput from "../components/LinkSourceInput";
import PlatformIcon from "../components/PlatformIcon";
import {
  confirmMeteredOperation,
  mediaDurationSeconds,
  textOperationUsage,
} from "../lib/meteredOperation";

const STEPS = [
  { key: "link", label: "链接选题" },
  { key: "script", label: "文案二创" },
  { key: "voice", label: "配音" },
  { key: "avatar", label: "数字人" },
  { key: "compose", label: "视频合成" },
  { key: "edit", label: "视频剪辑" },
  { key: "publish", label: "发布" },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

interface Wizard {
  sourceUrl: string;
  topic: string;
  originalText: string;
  rewrittenText: string;
  scriptText: string;
  scriptId: string;
  similarity: number | null;
  voiceId: string;
  avatarId: string;
  mode: "auto" | "manual";
  count: number;
  randomize: boolean;
  platforms: Platform[];
  publishAt: string;
  title: string;
  taskId: string;
}

const initialWizard: Wizard = {
  sourceUrl: "",
  topic: "",
  originalText: "",
  rewrittenText: "",
  scriptText: "",
  scriptId: "",
  similarity: null,
  voiceId: "",
  avatarId: "",
  mode: "auto",
  count: 1,
  randomize: false,
  platforms: [],
  publishAt: "",
  title: "",
  taskId: "",
};

interface OperationProgress {
  value: number;
  label: string;
  ariaLabel?: string;
  hint?: string;
}

function OperationProgressPanel({ progress }: { progress: OperationProgress }) {
  return (
    <div
      className="rounded-xl border border-brand-to/25 bg-brand-to/5 p-3"
      aria-live="polite"
    >
      <div className="mb-2 flex items-center justify-between gap-3 text-xs">
        <span className="text-text-2">{progress.label}</span>
        <span className="font-mono text-brand-to">{progress.value}%</span>
      </div>
      <div
        role="progressbar"
        aria-label={progress.ariaLabel ?? "视频转写进度"}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress.value}
        className="h-2 overflow-hidden rounded-full bg-white/10"
      >
        <div
          className="h-full rounded-full bg-brand-grad transition-[width] duration-500"
          style={{ width: `${progress.value}%` }}
        />
      </div>
      {progress.value < 100 && (
        <p className="mt-2 text-[11px] text-text-3">
          {progress.hint ?? "页面可以保持打开，失败不会扣除积分。"}
        </p>
      )}
    </div>
  );
}

export function buildPricePreviewRequest(
  input: Pick<Wizard, "sourceUrl" | "topic" | "scriptText" | "count">,
  modulePrices: Pick<ModulePrice, "module" | "billingUnit" | "unitSize">[],
  targetDurationSeconds = 60,
): PricePreviewRequest {
  const scriptLength = input.scriptText.trim().length;
  const durationSeconds = Math.max(
    1,
    targetDurationSeconds,
    Math.ceil(scriptLength * 0.28),
  );
  const textLength = Math.max(scriptLength, Math.ceil(durationSeconds / 0.28));
  const requestedModules = new Set([
    ...(input.sourceUrl && !input.scriptText.trim() ? ["asr"] : []),
    ...(input.topic && !input.scriptText.trim() ? ["topic_generation"] : []),
    // 已带确认文案（向导二创确认后）时 rewrite 步直接跳过，不计文案生成费
    ...(!input.scriptText.trim() ? ["script_generation"] : []),
    "tts",
    "digital_human",
    "hd_export",
  ]);

  const quantityFor = (price: Pick<ModulePrice, "billingUnit">): number => {
    if (
      price.billingUnit === "per_minute" ||
      price.billingUnit === "per_second"
    ) {
      return durationSeconds;
    }
    if (price.billingUnit === "per_1k_chars") return textLength;
    if (price.billingUnit === "per_1k_tokens") {
      return Math.max(1, Math.ceil(textLength / 2));
    }
    return 1;
  };

  return {
    items: modulePrices
      .filter((price) => requestedModules.has(price.module))
      .map((price) => ({ module: price.module, quantity: quantityFor(price) })),
  };
}

// ---------------- 第 1 步：链接/选题 ----------------

function StepLink({
  wiz,
  setWiz,
}: {
  wiz: Wizard;
  setWiz: (w: Wizard) => void;
}) {
  const [tab, setTab] = useState<"url" | "topic" | "script">(
    wiz.topic ? "topic" : wiz.scriptText ? "script" : "url",
  );
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<OperationProgress | null>(null);
  const loadQuota = useQuota((state) => state.load);

  const selectTab = (nextTab: "url" | "topic" | "script") => {
    setTab(nextTab);
    setWiz({
      ...wiz,
      sourceUrl: nextTab === "url" ? wiz.sourceUrl : "",
      topic: nextTab === "topic" ? wiz.topic : "",
      originalText: nextTab === "script" ? wiz.originalText : "",
      rewrittenText: nextTab === "script" ? wiz.rewrittenText : "",
      scriptText: nextTab === "script" ? wiz.scriptText : "",
      scriptId: nextTab === "script" ? wiz.scriptId : "",
    });
  };

  const upload = async (file: File) => {
    setUploading(true);
    setError("");
    setProgress({ value: 8, label: "正在读取媒体信息" });
    try {
      const seconds = await mediaDurationSeconds(file);
      setProgress({ value: 20, label: "正在获取本次转写报价" });
      const quoteId = await confirmMeteredOperation("asr", "上传转写", {
        seconds,
        assets: 1,
      });
      const res = await contentApi.parse(undefined, file, quoteId, (job) =>
        setProgress({
          value: job.progress,
          label: job.stage,
          ariaLabel: "视频转写真实进度",
        }),
      );
      if (res.transcript) {
        setWiz({
          ...wiz,
          originalText: res.transcript.text,
          rewrittenText: "",
          scriptText: res.transcript.text,
          scriptId: res.scriptId ?? "",
          sourceUrl: "",
          topic: "",
        });
        setProgress({ value: 100, label: "转写完成，文案已提取" });
      } else {
        setProgress(null);
        setError("未提取到文案，请检查文件是否包含清晰音轨");
      }
    } catch (e) {
      setProgress(null);
      setError(
        e instanceof HttpError
          ? e.body.message
          : e instanceof Error
            ? e.message
            : "视频转写失败，请稍后重试",
      );
    } finally {
      setUploading(false);
      void loadQuota();
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-1 rounded-xl bg-white/5 p-1">
        {(
          [
            ["url", "链接解析"],
            ["topic", "选题生成"],
            ["script", "直接写文案"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => selectTab(k)}
            className={`rounded-lg py-2 text-sm transition-colors ${tab === k ? "bg-brand-grad text-white" : "text-text-3 hover:text-text-1"}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "url" && (
        <div className="space-y-3">
          <LinkSourceInput
            value={wiz.sourceUrl}
            onChange={(v) =>
              setWiz({
                ...wiz,
                sourceUrl: v,
                topic: "",
                originalText: "",
                rewrittenText: "",
                scriptText: "",
                scriptId: "",
              })
            }
            onUpload={(f) => void upload(f)}
            uploading={uploading}
          />
          <p className="text-xs text-text-3">
            {uploading
              ? "解析上传中…"
              : "粘贴链接直接解析，或点输入框左侧图标上传本地视频/音频（视频号、解析失败时降级转写）"}
          </p>
          {progress && <OperationProgressPanel progress={progress} />}
          {error && (
            <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </div>
          )}
        </div>
      )}

      {tab === "topic" && (
        <div>
          <label className="label">输入选题方向，AI 自动生成口播文案</label>
          <input
            className="input h-14 text-base"
            placeholder="如：个体户报税 3 个坑 / 新房除甲醛真相…"
            value={wiz.topic}
            onChange={(e) =>
              setWiz({
                ...wiz,
                topic: e.target.value,
                sourceUrl: "",
                originalText: "",
                rewrittenText: "",
                scriptText: "",
                scriptId: "",
              })
            }
          />
        </div>
      )}

      {tab === "script" && (
        <div>
          <label className="label">直接粘贴/编写口播文案</label>
          <textarea
            className="input min-h-40 resize-y"
            placeholder="粘贴你的口播文案…"
            value={wiz.scriptText}
            onChange={(e) =>
              setWiz({
                ...wiz,
                originalText: e.target.value,
                rewrittenText: "",
                scriptText: e.target.value,
                scriptId: "",
                sourceUrl: "",
                topic: "",
              })
            }
          />
        </div>
      )}
    </div>
  );
}

// ---------------- 第 2 步：文案（转写/仿写/去重） ----------------

function StepScript({
  wiz,
  setWiz,
}: {
  wiz: Wizard;
  setWiz: (w: Wizard) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [operation, setOperation] = useState<
    "initial" | "rewrite" | "similarity" | null
  >(null);
  const [error, setError] = useState("");
  const [degraded, setDegraded] = useState(false);
  const [intensity, setIntensity] = useState<RewriteIntensity>("structure");
  const [customPrompt, setCustomPrompt] = useState("");
  const [structure, setStructure] = useState<Record<string, unknown> | null>(
    null,
  );
  const [outline, setOutline] = useState<string | null>(null);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [progress, setProgress] = useState<OperationProgress | null>(null);
  const startedInitialGeneration = useRef(false);
  const loadQuota = useQuota((state) => state.load);
  const currentIp = useIp((state) => state.current);

  // 首次进入：链接/选题 → 转写/生成文案
  useEffect(() => {
    if (wiz.scriptText || (!wiz.sourceUrl && !wiz.topic)) return;
    if (startedInitialGeneration.current) return;
    startedInitialGeneration.current = true;
    setLoading(true);
    setOperation("initial");
    setError("");
    setDegraded(false);
    const run = async () => {
      try {
        if (wiz.sourceUrl) {
          setProgress({ value: 10, label: "正在解析视频链接" });
          const durationSeconds = (await contentApi.probe(wiz.sourceUrl))
            .durationSeconds;
          setProgress({ value: 22, label: "正在获取本次转写报价" });
          const parseQuoteId = await confirmMeteredOperation(
            "asr",
            "链接转写",
            {
              seconds: durationSeconds,
              assets: 1,
            },
          );
          setProgress({ value: 50, label: "正在提取视频文案" });
          const res = await contentApi.parse(
            wiz.sourceUrl,
            undefined,
            parseQuoteId,
            (job) =>
              setProgress({
                value: job.progress,
                label: job.stage,
                ariaLabel: "视频转写真实进度",
              }),
          );
          if (res.degraded) setDegraded(true);
          const text = res.transcript?.text ?? "";
          if (!text) {
            setError("未提取到文案，请检查链接是否有效，或尝试上传本地视频");
            setProgress(null);
            return;
          }
          setWiz({
            ...wiz,
            originalText: text,
            rewrittenText: "",
            scriptText: text,
            scriptId: res.scriptId ?? "",
            similarity: null,
          });
          setProgress({ value: 100, label: "完整原文提取完成" });
        } else {
          const prompt = `请围绕选题「${wiz.topic}」生成 60 秒口播文案`;
          const quoteId = await confirmMeteredOperation(
            "script_generation",
            "生成口播文案",
            textOperationUsage(prompt),
          );
          const rw = await contentApi.rewrite(
            prompt,
            "theme",
            undefined,
            undefined,
            quoteId,
            (job) =>
              setProgress({
                value: job.progress,
                label: job.stage,
                ariaLabel: "文案生成真实进度",
              }),
          );
          setWiz({
            ...wiz,
            originalText: rw.text,
            rewrittenText: "",
            scriptText: rw.text,
            similarity: rw.similarity ?? null,
          });
          if (rw.structure) setStructure(rw.structure);
          if (rw.outline) setOutline(rw.outline);
        }
      } catch (e) {
        setProgress(null);
        setError(
          e instanceof HttpError
            ? e.body.message
            : "解析失败，请检查链接或稍后重试",
        );
      } finally {
        setLoading(false);
        setOperation(null);
        void loadQuota();
      }
    };
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rewrite = async () => {
    setLoading(true);
    setOperation("rewrite");
    setError("");
    try {
      const requirement = customPrompt.trim();
      const sourceText = wiz.originalText || wiz.scriptText;
      const quoteId = await confirmMeteredOperation(
        "script_generation",
        "仿写文案",
        textOperationUsage(
          requirement ? `${sourceText}\n${requirement}` : sourceText,
        ),
      );
      if (!quoteId) {
        setProgress(null);
        return;
      }
      const rw = await contentApi.rewrite(
        sourceText,
        intensity,
        requirement || undefined,
        wiz.scriptId || undefined,
        quoteId,
        (job) =>
          setProgress({
            value: job.progress,
            label: job.stage,
            ariaLabel: "IP 改写真实进度",
            hint: "结构分析、IP 大纲、完整改写与质量校验均在后台执行。",
          }),
      );
      setWiz({
        ...wiz,
        originalText: sourceText,
        rewrittenText: rw.text,
        scriptText: rw.text,
        similarity: rw.similarity ?? null,
      });
      if (rw.structure) setStructure(rw.structure);
      if (rw.outline) setOutline(rw.outline);
      setProgress({
        value: 100,
        label: "IP 改写完成",
        ariaLabel: "IP 改写真实进度",
      });
    } catch (e) {
      setProgress(null);
      setError(
        e instanceof HttpError
          ? e.body.message
          : "文案改写失败，请检查配置后重试",
      );
    } finally {
      setLoading(false);
      setOperation(null);
      void loadQuota();
    }
  };

  const checkSim = async () => {
    setLoading(true);
    setOperation("similarity");
    try {
      const quoteId = await confirmMeteredOperation(
        "script_generation",
        "检测相似度",
        textOperationUsage(wiz.scriptText),
      );
      if (!quoteId) return;
      const sim = await contentApi.similarity(wiz.scriptText, quoteId, (job) =>
        setProgress({
          value: job.progress,
          label: job.stage,
          ariaLabel: "文案分析真实进度",
        }),
      );
      setWiz({ ...wiz, similarity: sim.score });
      setProgress({
        value: 100,
        label: "文案分析完成",
        ariaLabel: "文案分析真实进度",
      });
    } finally {
      setLoading(false);
      setOperation(null);
    }
  };

  const simScore = wiz.similarity;
  const simColor =
    simScore === null
      ? ""
      : simScore < 30
        ? "text-success"
        : simScore < 60
          ? "text-warning"
          : "text-danger";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-text-2">仿写强度：</span>
        {(
          [
            ["light", "轻度润色"],
            ["structure", "结构重组"],
            ["theme", "主题改写"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setIntensity(k)}
            className={`chip ${intensity === k ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}
          >
            {label}
          </button>
        ))}
        <div className="flex-1" />
        <button
          onClick={checkSim}
          disabled={loading || !wiz.scriptText}
          className="btn-ghost px-3 py-1 text-xs"
        >
          去重检测
        </button>
        {simScore !== null && (
          <span className={`chip border-current/40 ${simColor}`}>
            去重分 {simScore.toFixed(0)}
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}
      {progress && <OperationProgressPanel progress={progress} />}
      {degraded && !error && (
        <div className="flex items-start gap-1.5 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          链接解析已降级处理（第三方服务不可用），结果可能不完整。请稍后重试或上传本地视频。
        </div>
      )}

      {/* 结构拆解 + 大纲（可折叠） */}
      {(structure || outline) && (
        <div className="rounded-xl border border-stroke bg-white/[0.02]">
          <button
            className="flex w-full items-center justify-between px-4 py-2.5 text-xs text-text-2"
            onClick={() => setShowAnalysis(!showAnalysis)}
          >
            <span className="flex items-center gap-1.5">
              <ChartColumn className="h-3.5 w-3.5" /> AI 结构拆解 & IP化大纲
            </span>
            <span className="flex items-center gap-1">
              {showAnalysis ? (
                <>
                  <ChevronUp className="h-3 w-3" /> 收起
                </>
              ) : (
                <>
                  <ChevronDown className="h-3 w-3" /> 展开
                </>
              )}
            </span>
          </button>
          {showAnalysis && (
            <div className="space-y-3 border-t border-stroke px-4 py-3 text-xs text-text-3">
              {structure && (
                <div>
                  <div className="mb-1 font-medium text-text-2">爆款结构：</div>
                  <div className="space-y-0.5">
                    {structure.hook_type != null && (
                      <div>
                        钩子：{String(structure.hook_type)} —{" "}
                        {String(structure.hook_text ?? "")}
                      </div>
                    )}
                    {Array.isArray(structure.pain_points) && (
                      <div>
                        痛点：{(structure.pain_points as string[]).join("、")}
                      </div>
                    )}
                    {Array.isArray(structure.value_points) && (
                      <div>
                        价值点：
                        {(structure.value_points as string[]).join("、")}
                      </div>
                    )}
                    {structure.cta_type != null && (
                      <div>CTA：{String(structure.cta_type)}</div>
                    )}
                    {structure.emotion_curve != null && (
                      <div>情绪曲线：{String(structure.emotion_curve)}</div>
                    )}
                  </div>
                </div>
              )}
              {outline && (
                <div>
                  <div className="mb-1 font-medium text-text-2">IP化大纲：</div>
                  <pre className="whitespace-pre-wrap font-sans">{outline}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div>
        <label className="label">提取原文（保留，可编辑）</label>
        <textarea
          aria-label="提取原文"
          className="input min-h-64 resize-y font-normal leading-relaxed"
          placeholder={loading ? "AI 正在生成文案…" : "口播文案"}
          value={wiz.originalText || wiz.scriptText}
          onChange={(e) => {
            const originalText = e.target.value;
            setWiz({
              ...wiz,
              originalText,
              scriptText: wiz.rewrittenText ? wiz.scriptText : originalText,
            });
          }}
          disabled={loading && !wiz.originalText && !wiz.scriptText}
        />
      </div>
      {wiz.rewrittenText && (
        <div className="rounded-xl border border-brand-to/30 bg-brand-to/5 p-3">
          <label className="label">IP 改写结果（后续成片使用）</label>
          <textarea
            aria-label="IP 改写结果"
            className="input min-h-64 resize-y font-normal leading-relaxed"
            value={wiz.rewrittenText}
            onChange={(event) =>
              setWiz({
                ...wiz,
                rewrittenText: event.target.value,
                scriptText: event.target.value,
              })
            }
          />
        </div>
      )}
      <div className="text-right text-xs text-text-3">
        {wiz.scriptText.length} 字 · 约{" "}
        {Math.ceil(wiz.scriptText.length * 0.28)} 秒
      </div>

      <div className="rounded-xl border border-stroke bg-white/[0.02] p-3">
        <div className="mb-2 text-xs text-text-2">
          当前 IP：
          <span className="font-medium text-text-1">
            {currentIp?.name ?? "未选择（将使用通用风格）"}
          </span>
        </div>
        <label className="label">自定义改写要求（可选）</label>
        <textarea
          className="input min-h-20 resize-y"
          placeholder="补充改写要求，如：保留案例，语气更克制"
          value={customPrompt}
          onChange={(event) => setCustomPrompt(event.target.value)}
        />
        <button
          onClick={rewrite}
          disabled={loading || !wiz.scriptText}
          className="btn-primary mt-3 w-full"
        >
          {operation === "initial"
            ? wiz.sourceUrl
              ? "等待原文提取完成"
              : "等待初稿生成完成"
            : operation === "rewrite"
              ? "正在按 IP 改写…"
              : operation === "similarity"
                ? "等待去重检测完成"
                : "按当前 IP 改写"}
        </button>
      </div>
    </div>
  );
}

// ---------------- 第 3/4 步：声音 / 数字人 ----------------

function StepVoice({
  wiz,
  setWiz,
}: {
  wiz: Wizard;
  setWiz: (w: Wizard) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["voices"],
    queryFn: () => voiceApi.list(),
  });
  // 只展示就绪声音：训练中/失败的声音无法用于合成
  const ready = (data ?? []).filter((v) => v.status === "ready");
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      {ready.map((v) => (
        <button
          key={v.id}
          onClick={() => setWiz({ ...wiz, voiceId: v.id })}
          className={`rounded-xl border p-4 text-left transition-all ${
            wiz.voiceId === v.id
              ? "border-brand-from/60 bg-brand-from/10"
              : "border-stroke bg-white/[0.03] hover:border-stroke-strong"
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-grad text-white">
              <Music className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{v.name}</div>
              <div className="text-xs text-text-3">
                {v.source === "clone" ? "克隆音色" : "内置音色"} · {v.gender}
              </div>
            </div>
          </div>
        </button>
      ))}
      {isLoading && (
        <div className="col-span-full py-8 text-center text-sm text-text-3">
          加载音色库…
        </div>
      )}
      {!isLoading && ready.length === 0 && (
        <div className="col-span-full py-8 text-center text-sm text-text-3">
          还没有就绪的声音，
          <Link className="text-brand-to hover:underline" to="/assets/voices">
            先去克隆一个 →
          </Link>
        </div>
      )}
    </div>
  );
}

function StepAvatar({
  wiz,
  setWiz,
}: {
  wiz: Wizard;
  setWiz: (w: Wizard) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["avatars"],
    queryFn: () => avatarApi.list(),
  });
  // 只展示就绪数字人：合成侧要求 status=ready 才能驱动
  const ready = (data ?? []).filter((a) => a.status === "ready");
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      {ready.map((a) => (
        <button
          key={a.id}
          onClick={() => setWiz({ ...wiz, avatarId: a.id })}
          className={`rounded-xl border p-4 text-left transition-all ${
            wiz.avatarId === a.id
              ? "border-brand-from/60 bg-brand-from/10"
              : "border-stroke bg-white/[0.03] hover:border-stroke-strong"
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/10 text-white">
              <Smile className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{a.name}</div>
              <div className="text-xs text-text-3">
                {a.source === "clone"
                  ? "克隆形象"
                  : `公共库 · ${a.style ?? "通用"}`}
              </div>
            </div>
          </div>
        </button>
      ))}
      {isLoading && (
        <div className="col-span-full py-8 text-center text-sm text-text-3">
          加载数字人…
        </div>
      )}
      {!isLoading && ready.length === 0 && (
        <div className="col-span-full py-8 text-center text-sm text-text-3">
          还没有就绪的数字人，
          <Link className="text-brand-to hover:underline" to="/assets/avatars">
            先去训练一个 →
          </Link>
        </div>
      )}
    </div>
  );
}

// ---------------- 第 6 步：视频剪辑（成片预览 + 可跳过） ----------------

function StepEdit({
  finalVideoKey,
  onSkip,
}: {
  finalVideoKey: string;
  onSkip: () => void;
}) {
  const navigate = useNavigate();
  return (
    <div className="space-y-4">
      {finalVideoKey && (
        <div>
          <label className="label">成片预览</label>
          <video
            src={`/media/${finalVideoKey}`}
            controls
            playsInline
            preload="metadata"
            className="max-h-72 w-full rounded-xl bg-black"
            aria-label="剪辑成片预览"
          />
        </div>
      )}
      <div className="glass flex flex-col items-center gap-4 py-8 text-center">
        <span className="text-text-2">
          <Scissors className="h-9 w-9" />
        </span>
        <div>
          <div className="font-medium">可先去剪辑台精修，也可直接发布</div>
          <p className="mt-1 text-sm text-text-3">
            字幕样式 / BGM 三模式 / 封面编辑，剪辑台支持对成片精修
          </p>
        </div>
        <div className="flex gap-3">
          <button className="btn-ghost" onClick={() => navigate("/editor")}>
            先去剪辑台看看
          </button>
          <button className="btn-primary" onClick={onSkip}>
            跳过，进入发布配置 →
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------- 第 7 步：发布配置（对着已生成的成片选平台发布） ----------------

function StepPublish({
  wiz,
  setWiz,
  finalVideoKey,
}: {
  wiz: Wizard;
  setWiz: (w: Wizard) => void;
  finalVideoKey: string;
}) {
  const { data: capabilities } = useQuery({
    queryKey: ["publish-capabilities"],
    queryFn: () => publishApi.capabilities(),
  });
  const toggle = (p: Platform) =>
    setWiz({
      ...wiz,
      platforms: wiz.platforms.includes(p)
        ? wiz.platforms.filter((x) => x !== p)
        : [...wiz.platforms, p],
    });

  if (!finalVideoKey) {
    return (
      <div className="rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-warning">
        成片尚未生成，请先回到「视频合成」步完成合成后再配置发布。
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="label">成片预览</label>
        <video
          src={`/media/${finalVideoKey}`}
          controls
          playsInline
          preload="metadata"
          className="max-h-72 w-full rounded-xl bg-black"
          aria-label="待发布成片预览"
        />
      </div>
      <div>
        <label className="label">
          发布平台（可仅生成不发布，稍后在发布管理手动发）
        </label>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {PUBLISH_PLATFORMS.map((p) => {
            const capability = capabilities?.find(
              (item) => item.platform === p,
            );
            return (
              <button
                key={p}
                onClick={() => toggle(p)}
                className={`flex items-center justify-center gap-2 rounded-xl border p-3.5 text-sm transition-all ${
                  wiz.platforms.includes(p)
                    ? "border-brand-from/60 bg-brand-from/10 text-text-1"
                    : "border-stroke bg-white/[0.03] text-text-3"
                }`}
              >
                <PlatformIcon platform={p} size={18} />
                <span>
                  {PLATFORM_NAMES[p]}
                  <span className="block text-[10px] opacity-70">
                    {capability?.automaticEnabled ? "自动发布" : "人工发布包"}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
      <div>
        <label className="label">视频标题（F-403 自动候选，可改）</label>
        <input
          className="input"
          placeholder="留空则取文案首句"
          value={wiz.title}
          onChange={(e) => setWiz({ ...wiz, title: e.target.value })}
        />
      </div>
      <div>
        <label className="label">定时发布（F-503，留空立即发布）</label>
        <input
          type="datetime-local"
          className="input"
          value={wiz.publishAt}
          onChange={(e) => setWiz({ ...wiz, publishAt: e.target.value })}
        />
      </div>
    </div>
  );
}

// ---------------- 向导主框架 ----------------

export default function CreatePage() {
  const [params, setParams] = useSearchParams();
  const step = (params.get("step") ?? "link") as StepKey;
  const stepIdx = STEPS.findIndex((s) => s.key === step);
  const [wiz, setWiz] = useState<Wizard>(initialWizard);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [quote, setQuote] = useState<PricePreview | null>(null);
  const { current } = useIp();
  const navigate = useNavigate();
  const {
    data: moduleCatalog,
    isError: catalogFailed,
    refetch: refetchCatalog,
  } = useQuery({
    queryKey: ["catalog", "module-prices"],
    queryFn: () => catalogApi.modulePrices(),
  });

  // 合成步全自动：进入即报价并创建任务，ref 防止 StrictMode/重渲染重复触发
  const autoStartRef = useRef(false);

  // 合成任务实时追踪：WS 推送（useTasks）优先，3s 轮询兜底
  const liveTask = useTasks((s) =>
    wiz.taskId ? s.tasks[wiz.taskId] : undefined,
  );
  const { data: fetchedTask } = useQuery({
    queryKey: ["task", wiz.taskId],
    queryFn: () => pipelineApi.get(wiz.taskId),
    enabled: Boolean(wiz.taskId),
    refetchInterval: (q) => {
      // 首拉失败时也持续重试，避免 WS 不可用 + 首次拉取失败时面板永久卡住
      if (!q.state.data) return 3000;
      const s = q.state.data.status;
      return s === "pending" || s === "running" || s === "waiting_confirm"
        ? 3000
        : false;
    },
    // 标签页切后台时也保持轮询，切回即见最新进度
    refetchIntervalInBackground: true,
  });
  const task = wiz.taskId ? (liveTask ?? fetchedTask) : undefined;
  const composeArtifacts = task?.steps.find(
    (s) => s.step === "compose",
  )?.artifacts;
  const finalVideoKey = composeArtifacts?.final_video_key ?? "";
  const coverKey = composeArtifacts?.cover_key ?? "";

  // 合成前置产物校验：直达本步缺料时引导补齐对应步骤，绝不静默自动扣费
  const composeGap = !current
    ? { text: "请先在左侧栏选择一个 IP", step: null }
    : wiz.scriptText.trim().length < 10
      ? {
          text: "缺少口播文案，请先完成「文案二创」步",
          step: "script" as StepKey,
        }
      : !wiz.voiceId
        ? { text: "缺少声音，请先完成「配音」步", step: "voice" as StepKey }
        : !wiz.avatarId
          ? {
              text: "缺少数字人，请先完成「数字人」步",
              step: "avatar" as StepKey,
            }
          : null;

  useEffect(() => {
    setQuote(null);
  }, [
    wiz.sourceUrl,
    wiz.topic,
    wiz.scriptText,
    wiz.count,
    current?.videoDuration,
  ]);

  // Hero 入口参数带入；文案工坊「用它成片」带 scriptId 直接载入文案；资产页「去成片」带 voiceId/avatarId 预选
  useEffect(() => {
    const url = params.get("url");
    const topic = params.get("topic");
    const scriptId = params.get("scriptId");
    const voiceId = params.get("voiceId");
    const avatarId = params.get("avatarId");
    if (voiceId || avatarId) {
      setWiz((w) => ({
        ...w,
        voiceId: voiceId ?? w.voiceId,
        avatarId: avatarId ?? w.avatarId,
      }));
    }
    if (scriptId) {
      void contentApi.script(scriptId).then((s) => {
        setWiz((w) => ({
          ...w,
          originalText: s.originalText,
          rewrittenText: s.rewrittenText || "",
          scriptText: s.rewrittenText || s.originalText,
          scriptId: s.id,
        }));
      });
      return;
    }
    if (url || topic) {
      setWiz((w) => ({ ...w, sourceUrl: url ?? "", topic: topic ?? "" }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 预选当前 IP 绑定的默认声音/数字人（URL 参数与手动选择优先）
  useEffect(() => {
    if (!current) return;
    setWiz((w) => ({
      ...w,
      voiceId: w.voiceId || current.voiceId || "",
      avatarId: w.avatarId || current.avatarId || "",
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id]);

  const goStep = (key: StepKey) => setParams({ step: key });

  // 进入「视频合成」步后自动开始：前置产物齐备且模块价格目录就绪才报价 + 创建任务
  useEffect(() => {
    if (step !== "compose" || wiz.taskId || autoStartRef.current) return;
    if (composeGap || !moduleCatalog) return;
    void startCompose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, wiz.taskId, composeGap, moduleCatalog]);

  // 任务已创建：合成步不再原地展示进度条，直接跳转任务详情页承接进度/取消/剪辑/发布
  useEffect(() => {
    if (step === "compose" && wiz.taskId) {
      navigate(`/tasks/${wiz.taskId}`, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, wiz.taskId]);

  // 模块价格目录加载失败时给出可重试的错误，避免停留在「准备中…」死局
  useEffect(() => {
    if (step === "compose" && !wiz.taskId && catalogFailed && !moduleCatalog) {
      setError("模块价格目录加载失败，请重试");
    }
  }, [step, wiz.taskId, catalogFailed, moduleCatalog]);

  const canNext = (): boolean => {
    if (step === "link")
      return Boolean(wiz.sourceUrl || wiz.topic || wiz.scriptText);
    if (step === "script") return wiz.scriptText.trim().length >= 10;
    if (step === "voice") return Boolean(wiz.voiceId);
    if (step === "avatar") return Boolean(wiz.avatarId);
    // 合成步：成片生成后才能进入后续剪辑/发布
    if (step === "compose") return Boolean(finalVideoKey);
    return true;
  };

  const next = () => {
    const s = STEPS[stepIdx + 1];
    if (s) goStep(s.key);
  };
  const prev = () => {
    const s = STEPS[stepIdx - 1];
    if (s) goStep(s.key);
  };

  /** 合成步全自动提交：报价 → 校验余额 → 创建流水线任务，成功后跳转任务详情页 */
  const startCompose = async () => {
    if (!current) {
      setError("请先在左侧栏选择 IP");
      return;
    }
    autoStartRef.current = true;
    setSubmitting(true);
    setError("");
    try {
      // 目录首拉失败后手动重试时补拉一次，保证「重试合成」可自愈
      let catalogItems = moduleCatalog?.items;
      if (!catalogItems) {
        catalogItems = (await refetchCatalog()).data?.items;
      }
      if (!catalogItems) {
        setError("模块价格目录加载失败，请重试");
        return;
      }
      const request = buildPricePreviewRequest(
        wiz,
        catalogItems,
        current.videoDuration || 60,
      );
      if (request.items.length === 0) {
        setError("当前没有已发布的模块积分价格，请联系管理员配置价格版本");
        return;
      }
      const freshQuote = await billingApi.pricePreview(request);
      setQuote(freshQuote);
      const estimatedTotal =
        freshQuote.estimatedPoints * Math.max(1, wiz.count);
      if (freshQuote.availablePoints < estimatedTotal) {
        setError("积分余额不足，请先兑换积分包或续费套餐");
        return;
      }
      const tasks = await pipelineApi.create({
        ipId: current.id,
        sourceUrl: wiz.sourceUrl || undefined,
        topic: wiz.topic || undefined,
        scriptText: wiz.scriptText || undefined,
        voiceId: wiz.voiceId || undefined,
        avatarId: wiz.avatarId || undefined,
        mode: wiz.mode,
        platforms: [],
        randomize: wiz.randomize,
        count: wiz.count,
        quoteId: freshQuote.quoteId,
      });
      const first = tasks[0];
      if (!first) {
        setError("任务创建失败，请重试");
        return;
      }
      // 函数式更新，避免覆盖提交期间用户对向导的其它修改；批量任务可在任务中心查看
      setWiz((w) => ({ ...w, taskId: first.id }));
      navigate(`/tasks/${first.id}`);
    } catch (e) {
      setError(
        e instanceof HttpError ? e.body.message : "合成启动失败，请重试",
      );
    } finally {
      setSubmitting(false);
    }
  };

  /** 发布步提交：对已生成的成片创建发布任务；未选平台则直接完成 */
  const publishVideo = async () => {
    if (!finalVideoKey) {
      setError("成片尚未生成，请先完成合成步");
      return;
    }
    if (wiz.platforms.length === 0) {
      navigate(wiz.taskId ? `/tasks/${wiz.taskId}` : "/tasks");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await publishApi.createJobs({
        taskId: wiz.taskId || undefined,
        platforms: wiz.platforms,
        title: (
          wiz.title.trim() ||
          wiz.scriptText.split(/[。！？!?\n]/)[0] ||
          "口播成片"
        ).slice(0, 30),
        videoKey: finalVideoKey,
        coverKey: coverKey || undefined,
        publishAt: wiz.publishAt
          ? new Date(wiz.publishAt).toISOString()
          : undefined,
      });
      navigate("/publish/jobs");
    } catch (e) {
      setError(
        e instanceof HttpError ? e.body.message : "创建发布任务失败，请重试",
      );
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="glass-strong p-6">
        <h1 className="mb-4 text-lg font-bold">
          第 {stepIdx + 1} 步 · {STEPS[stepIdx]?.label}
        </h1>

        {step === "link" && <StepLink wiz={wiz} setWiz={setWiz} />}
        {step === "script" && <StepScript wiz={wiz} setWiz={setWiz} />}
        {step === "voice" && <StepVoice wiz={wiz} setWiz={setWiz} />}
        {step === "avatar" && <StepAvatar wiz={wiz} setWiz={setWiz} />}
        {step === "compose" &&
          (wiz.taskId ? (
            // 任务已创建：effect 会立即跳转任务详情页，这里仅作跳转前的占位
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <LoaderCircle className="h-8 w-8 animate-spin text-info" />
              <div className="text-sm text-text-3">
                任务已创建，正在进入任务详情…
              </div>
            </div>
          ) : composeGap ? (
            // 直达合成步但缺前置产物：引导补齐，不自动扣费
            <div className="glass flex flex-col items-center gap-3 py-10 text-center">
              <TriangleAlert className="h-8 w-8 text-warning" />
              <div className="font-medium">暂无法开始合成</div>
              <p className="text-sm text-text-3">{composeGap.text}</p>
            </div>
          ) : (
            // 全自动：进入本步即自动报价并开始合成，无需手动配置
            <div className="space-y-4">
              <div className="glass flex flex-col items-center gap-3 py-10 text-center">
                {error ? (
                  <TriangleAlert className="h-8 w-8 text-danger" />
                ) : (
                  <LoaderCircle className="h-8 w-8 animate-spin text-info" />
                )}
                <div className="font-medium">
                  {error
                    ? "合成启动失败"
                    : submitting
                      ? "正在启动数字人合成…"
                      : "正在准备合成参数…"}
                </div>
                <p className="text-sm text-text-3">
                  自动计算所需积分并创建合成任务，创建后自动进入任务详情页
                </p>
                {quote && (
                  <p className="text-xs text-text-3">
                    预计消耗{" "}
                    <span className="font-mono">
                      {quote.estimatedPoints * Math.max(1, wiz.count)}
                    </span>{" "}
                    点 · 可用积分{" "}
                    <span className="font-mono">
                      {quote.availablePoints.toLocaleString()}
                    </span>
                  </p>
                )}
              </div>
            </div>
          ))}
        {step === "edit" && (
          <StepEdit finalVideoKey={finalVideoKey} onSkip={next} />
        )}
        {step === "publish" && (
          <StepPublish
            wiz={wiz}
            setWiz={setWiz}
            finalVideoKey={finalVideoKey}
          />
        )}

        {error && (
          <div className="mt-4 rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        {/* 底部操作条 */}
        {step !== "edit" && (
          <div className="mt-6 flex items-center justify-between border-t border-stroke pt-4">
            <button
              className="btn-ghost"
              onClick={prev}
              disabled={stepIdx === 0 || submitting}
            >
              ← 上一步
            </button>
            {step === "compose" && !wiz.taskId && composeGap ? (
              <button
                className="btn-primary px-8"
                onClick={() => composeGap.step && goStep(composeGap.step)}
                disabled={!composeGap.step}
              >
                去补齐 →
              </button>
            ) : step === "compose" && !wiz.taskId ? (
              <button
                className="btn-primary flex items-center gap-1.5 px-8"
                onClick={() => void startCompose()}
                disabled={submitting || !error}
              >
                {submitting ? (
                  "正在启动合成…"
                ) : error ? (
                  <>
                    <Zap className="h-4 w-4" />
                    重试合成
                  </>
                ) : (
                  "准备中…"
                )}
              </button>
            ) : step !== "publish" ? (
              <button
                className="btn-primary"
                onClick={next}
                disabled={!canNext()}
              >
                {step === "compose" && !finalVideoKey
                  ? "等待成片生成…"
                  : "下一步 →"}
              </button>
            ) : (
              <button
                className="btn-primary flex items-center gap-1.5 px-8"
                onClick={publishVideo}
                disabled={submitting || !finalVideoKey}
              >
                {submitting ? (
                  "提交中…"
                ) : wiz.platforms.length > 0 ? (
                  <>
                    <Zap className="h-4 w-4" />
                    创建发布任务 ×{wiz.platforms.length}
                  </>
                ) : (
                  "完成，稍后手动发布"
                )}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
