import { contentApi } from "@oral/api-client";
import type { RewriteIntensity } from "@oral/types";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  confirmMeteredOperation,
  textOperationUsage,
} from "../lib/meteredOperation";

/** 文案详情：原文/仿写对照、仿写强度三档、去重高亮（F-102~F-106） */
export default function ScriptDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { data: script } = useQuery({
    queryKey: ["script", id],
    queryFn: () => contentApi.script(id),
  });
  const [text, setText] = useState("");
  const [intensity, setIntensity] = useState<RewriteIntensity>("structure");
  const [sim, setSim] = useState<{
    score: number;
    spans: { text: string; start: number; end: number }[];
  } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (script) {
      setText(script.rewrittenText || script.originalText);
      setSim(null);
    }
  }, [script]);

  if (!script)
    return <div className="py-16 text-center text-text-3">加载中…</div>;

  const rewrite = async () => {
    setLoading(true);
    try {
      const quoteId = await confirmMeteredOperation(
        "script_generation",
        "仿写文案",
        textOperationUsage(text),
      );
      if (!quoteId) return;
      const rw = await contentApi.rewrite(
        text,
        intensity,
        undefined,
        id,
        quoteId,
      );
      setText(rw.text);
      setSim(
        rw.similarity == null ? null : { score: rw.similarity, spans: [] },
      );
    } finally {
      setLoading(false);
    }
  };

  const checkSim = async () => {
    setLoading(true);
    try {
      const quoteId = await confirmMeteredOperation(
        "script_generation",
        "检测相似度",
        textOperationUsage(text),
      );
      if (!quoteId) return;
      const s = await contentApi.similarity(text, quoteId);
      setSim({ score: s.score, spans: s.duplicatedSpans });
    } finally {
      setLoading(false);
    }
  };

  /** 去重高亮渲染：重复片段标红 */
  const renderHighlighted = () => {
    if (!sim || sim.spans.length === 0) return <span>{text}</span>;
    const parts: React.ReactNode[] = [];
    let cursor = 0;
    [...sim.spans]
      .sort((a, b) => a.start - b.start)
      .forEach((span, i) => {
        if (span.start > cursor)
          parts.push(
            <span key={`t${i}`}>{text.slice(cursor, span.start)}</span>,
          );
        parts.push(
          <mark
            key={`m${i}`}
            className="rounded bg-danger/25 px-0.5 text-danger"
            title="重复片段"
          >
            {text.slice(span.start, span.end)}
          </mark>,
        );
        cursor = span.end;
      });
    if (cursor < text.length)
      parts.push(<span key="tail">{text.slice(cursor)}</span>);
    return parts;
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(-1)}
          className="btn-ghost px-3 py-1.5 text-sm"
        >
          ← 返回
        </button>
        <h1 className="min-w-0 flex-1 truncate text-xl font-bold">
          {script.title || "文案详情"}
        </h1>
        <Link
          to={`/create?step=script&scriptId=${id}`}
          className="btn-primary text-sm"
        >
          用它成片 →
        </Link>
      </div>

      {/* 工具条 */}
      <div className="glass flex flex-wrap items-center gap-2 p-3">
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
          onClick={rewrite}
          disabled={loading}
          className="btn-ghost px-3 py-1 text-xs"
        >
          一键仿写
        </button>
        <button
          onClick={checkSim}
          disabled={loading}
          className="btn-ghost px-3 py-1 text-xs"
        >
          去重检测
        </button>
        {sim && (
          <span
            className={`chip border-current/40 ${sim.score < 30 ? "text-success" : sim.score < 60 ? "text-warning" : "text-danger"}`}
          >
            去重分 {sim.score.toFixed(0)}
          </span>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 原文 */}
        <div className="glass p-4">
          <div className="mb-2 text-xs font-medium text-text-3">原始转写</div>
          <div className="max-h-96 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-text-2">
            {script.originalText || "（无原文）"}
          </div>
        </div>

        {/* 仿写稿（可编辑） */}
        <div className="glass p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-text-3">
              仿写稿（可编辑）
            </span>
            <span className="text-[11px] text-text-3">{text.length} 字</span>
          </div>
          <textarea
            className="input min-h-80 resize-y border-transparent bg-transparent p-0 leading-relaxed focus:bg-transparent"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setSim(null);
            }}
          />
        </div>
      </div>

      {/* 去重高亮视图 */}
      {sim && (
        <div className="glass p-4">
          <div className="mb-2 text-xs font-medium text-text-3">
            去重高亮（红色为重复片段）
          </div>
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-text-2">
            {renderHighlighted()}
          </div>
        </div>
      )}
    </div>
  );
}
