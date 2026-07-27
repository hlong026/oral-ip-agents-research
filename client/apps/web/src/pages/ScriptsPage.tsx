import { contentApi, HttpError } from "@oral/api-client";
import { useRelativeTime } from "@oral/hooks";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import LinkSourceInput from "../components/LinkSourceInput";
import {
  confirmMeteredOperation,
  mediaDurationSeconds,
  textOperationUsage,
} from "../lib/meteredOperation";

/** 新建文案面板：链接/上传提取、选题生成、直接编写三入口，产物统一落文案资产 */
function NewScriptPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<"url" | "topic" | "script">("url");
  const [url, setUrl] = useState("");
  const [topic, setTopic] = useState("");
  const [text, setText] = useState("");
  const [topics, setTopics] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const fail = (e: unknown, fallback: string) =>
    setError(e instanceof HttpError ? e.body.message : fallback);

  /** 链接/上传 → 解析落库 → 详情页 */
  const extract = async (file?: File) => {
    if (!file && !url.trim()) return;
    setBusy(true);
    setError("");
    try {
      const seconds = file
        ? await mediaDurationSeconds(file)
        : (await contentApi.probe(url.trim())).durationSeconds;
      const quoteId = await confirmMeteredOperation("asr", "提取文案", {
        seconds,
        assets: 1,
      });
      if (!quoteId) return;
      const res = await contentApi.parse(
        file ? undefined : url.trim(),
        file,
        quoteId,
      );
      if (res.scriptId) {
        navigate(`/scripts/${res.scriptId}`);
      } else {
        setError("解析失败，可重试或改上传本地文件");
      }
    } catch (e) {
      fail(e, "解析失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  /** 选题：先生成候选选题；确认后 AI 成稿落库 → 详情页 */
  const genTopics = async () => {
    if (!topic.trim()) return;
    setBusy(true);
    setError("");
    try {
      const keyword = topic.trim();
      const quoteId = await confirmMeteredOperation(
        "topic_generation",
        "生成选题",
        textOperationUsage(keyword),
      );
      if (!quoteId) return;
      const res = await contentApi.topics(keyword, quoteId);
      setTopics(res.topics);
    } catch (e) {
      fail(e, "选题生成失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  const genScript = async (picked: string) => {
    setBusy(true);
    setError("");
    try {
      const prompt = `请围绕选题「${picked}」生成 60 秒口播文案`;
      const quoteId = await confirmMeteredOperation(
        "script_generation",
        "生成文案",
        textOperationUsage(prompt),
      );
      if (!quoteId) return;
      const rw = await contentApi.rewrite(
        prompt,
        "theme",
        undefined,
        undefined,
        quoteId,
      );
      const s = await contentApi.createScript({
        title: picked,
        text: rw.text,
        platform: "topic",
        topic: picked,
      });
      navigate(`/scripts/${s.id}`);
    } catch (e) {
      fail(e, "文案生成失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  /** 直接编写 → 落库 → 详情页 */
  const saveManual = async () => {
    if (text.trim().length < 10) return;
    setBusy(true);
    setError("");
    try {
      const s = await contentApi.createScript({
        text: text.trim(),
        platform: "manual",
      });
      navigate(`/scripts/${s.id}`);
    } catch (e) {
      fail(e, "保存失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="glass-strong space-y-4 p-5">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">新建文案</h2>
        <button
          className="btn-ghost flex items-center gap-1 px-2.5 py-1 text-xs"
          onClick={onClose}
        >
          收起 <X className="h-3 w-3" />
        </button>
      </div>
      <div className="grid grid-cols-3 gap-1 rounded-xl bg-white/5 p-1">
        {(
          [
            ["url", "链接/上传提取"],
            ["topic", "选题生成"],
            ["script", "直接编写"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`rounded-lg py-2 text-sm transition-colors ${tab === k ? "bg-brand-grad text-white" : "text-text-3 hover:text-text-1"}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "url" && (
        <div className="space-y-3">
          <LinkSourceInput
            value={url}
            onChange={setUrl}
            onUpload={(f) => void extract(f)}
            uploading={busy}
            onEnter={() => void extract()}
          />
          <button
            className="btn-primary w-full"
            disabled={busy || !url.trim()}
            onClick={() => void extract()}
          >
            {busy ? "提取中…" : "提取文案 →"}
          </button>
        </div>
      )}

      {tab === "topic" && (
        <div className="space-y-3">
          <div className="flex gap-2">
            <input
              className="input flex-1"
              placeholder="输入选题方向，如：个体户报税 3 个坑"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void genTopics()}
            />
            <button
              className="btn-ghost shrink-0"
              disabled={busy || !topic.trim()}
              onClick={() => void genTopics()}
            >
              生成选题
            </button>
          </div>
          {topics.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs text-text-3">
                选一个选题，AI 直接成稿并入库：
              </div>
              {topics.map((t) => (
                <button
                  key={t}
                  disabled={busy}
                  onClick={() => void genScript(t)}
                  className="card-hover block w-full rounded-xl border border-stroke bg-white/[0.03] px-3.5 py-2.5 text-left text-sm"
                >
                  {t}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "script" && (
        <div className="space-y-3">
          <textarea
            className="input min-h-32 resize-y"
            placeholder="粘贴/编写你的口播文案（≥10 字）…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button
            className="btn-primary w-full"
            disabled={busy || text.trim().length < 10}
            onClick={() => void saveManual()}
          >
            {busy ? "保存中…" : "保存到文案工坊 →"}
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}
    </div>
  );
}

/** 文案工坊（F-102~F-106：转写/仿写/去重资产库） */
export default function ScriptsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["scripts"],
    queryFn: () => contentApi.scripts(),
  });
  const [params, setParams] = useSearchParams();
  const [showNew, setShowNew] = useState(params.get("new") === "1");
  const navigate = useNavigate();

  // 支持 /scripts?new=1 外部入口（如 Hero 提取文案引导）
  useEffect(() => {
    if (params.get("new") === "1") {
      setShowNew(true);
      params.delete("new");
      setParams(params, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">文案工坊</h1>
          <p className="mt-1 text-sm text-text-3">
            解析转写、AI 仿写、去重检测的全部文案资产
          </p>
        </div>
        <button className="btn-primary" onClick={() => setShowNew((v) => !v)}>
          {showNew ? "收起面板" : "+ 新建文案"}
        </button>
      </div>

      {showNew && <NewScriptPanel onClose={() => setShowNew(false)} />}

      {isLoading && (
        <div className="py-16 text-center text-text-3">加载中…</div>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(data ?? []).map((s) => (
          <ScriptCard
            key={s.id}
            script={s}
            onOpen={() => navigate(`/scripts/${s.id}`)}
          />
        ))}
      </div>

      {!isLoading && (data ?? []).length === 0 && !showNew && (
        <div className="glass py-16 text-center text-text-3">
          还没有文案资产，
          <button
            className="text-brand-to hover:underline"
            onClick={() => setShowNew(true)}
          >
            从链接/选题开始 →
          </button>
        </div>
      )}
      {!isLoading && (data ?? []).length === 0 && (
        <div className="text-center text-xs text-text-3">
          也可以在工作台 Hero 粘贴链接，一键「提取文案」直达这里 ·
          <Link
            to="/create?step=link"
            className="text-brand-to hover:underline"
          >
            去一键成片 →
          </Link>
        </div>
      )}
    </div>
  );
}

function ScriptCard({
  script,
  onOpen,
}: {
  script: {
    id: string;
    title: string;
    platform: string;
    rewrittenText: string;
    originalText: string;
    similarityScore: number;
    createdAt: string;
  };
  onOpen: () => void;
}) {
  const rel = useRelativeTime(script.createdAt);
  const sim = script.similarityScore;
  const simColor =
    sim < 30
      ? "text-success border-success/40"
      : sim < 60
        ? "text-warning border-warning/40"
        : "text-danger border-danger/40";
  const text = script.rewrittenText || script.originalText;

  return (
    <button
      onClick={onOpen}
      className="glass card-hover flex flex-col p-4 text-left"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {script.title || "未命名文案"}
        </span>
        <span className={`chip shrink-0 ${simColor}`}>
          去重 {sim.toFixed(0)}
        </span>
      </div>
      <p className="line-clamp-3 flex-1 text-sm leading-relaxed text-text-2">
        {text}
      </p>
      <div className="mt-3 flex items-center justify-between text-[11px] text-text-3">
        <span className="chip">{script.platform || "手动"}</span>
        <span>{rel}</span>
      </div>
    </button>
  );
}
