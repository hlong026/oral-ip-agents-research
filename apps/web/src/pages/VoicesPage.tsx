import { HttpError, personaApi, voiceApi } from "@oral/api-client";
import { useIp } from "@oral/stores";
import type { Voice } from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import AssetNav from "../components/AssetNav";
import {
  confirmMeteredOperation,
  textOperationUsage,
} from "../lib/meteredOperation";

/** 克隆新声音表单（合规红线：强制 consent 授权勾选，凭证随克隆任务存证） */
function CloneForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
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
      // 授权凭证：勾选即代表确认合法授权，生成 consent_token 随任务存证
      const consentToken = `consent-${Date.now()}`;
      const quoteId = await confirmMeteredOperation("voice_clone", "声音克隆", {
        assets: 1,
      });
      if (!quoteId) return;
      await voiceApi.clone(name.trim(), consentToken, file, quoteId);
      setName("");
      setFile(null);
      setConsent(false);
      onDone();
    } catch (e) {
      setError(
        e instanceof HttpError ? e.body.message : "克隆发起失败，请重试",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="glass-strong space-y-3 p-5" id="clone">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">克隆一个新声音</h2>
        <span className="text-xs text-text-3">
          MiniMax Speech-02 · 约 10 分钟
        </span>
      </div>
      <div>
        <label className="label">声音名称</label>
        <input
          className="input"
          placeholder="例：李老师 · 直播切片声"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <label className="label">声音样本（1–5 分钟清晰人声，WAV/MP3）</label>
        <button
          className="btn-ghost w-full border-dashed py-5 text-text-3"
          onClick={() => fileRef.current?.click()}
        >
          {file ? `已选择：${file.name}` : "⬆ 点击选择音频文件"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="audio/*,.wav,.mp3,.m4a"
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
          我确认拥有该声音的合法授权（F-202 合规要求），授权凭证 consent_token
          将随克隆任务一并存证。
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
        {busy ? "克隆任务创建中…" : "开始克隆"}
      </button>
    </div>
  );
}

/** 试听台（TTS 即时合成，返回字级时间戳） */
function Playground({
  voices,
  defaultVoiceId,
}: {
  voices: Voice[];
  defaultVoiceId?: string;
}) {
  const [voiceId, setVoiceId] = useState(defaultVoiceId ?? "");
  const [text, setText] = useState("我是李老师，做财税 12 年，今天不绕弯子。");
  const [speed, setSpeed] = useState(1.0);
  const [busy, setBusy] = useState(false);
  const [audioUrl, setAudioUrl] = useState("");
  const [error, setError] = useState("");
  const ready = voices.filter((v) => v.status === "ready");
  const selected = voiceId || ready[0]?.id || "";

  const run = async () => {
    if (!selected || !text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const content = text.trim();
      const quoteId = await confirmMeteredOperation(
        "tts",
        "语音合成试听",
        textOperationUsage(content),
      );
      if (!quoteId) return;
      const res = await voiceApi.synthesize(selected, content, speed, quoteId);
      setAudioUrl(res.audioUrl);
    } catch (e) {
      setError(e instanceof HttpError ? e.body.message : "合成失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="glass space-y-3 p-5">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">试听台</h2>
        <span className="text-xs text-text-3">TTS 即时合成</span>
      </div>
      <textarea
        className="input min-h-20"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="输入任意文案，用选中的声音即时合成试听……"
      />
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="input h-10 flex-1 px-3 py-0 text-sm"
          value={selected}
          onChange={(e) => setVoiceId(e.target.value)}
        >
          {ready.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
        <select
          className="input h-10 w-24 px-3 py-0 text-sm"
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
        >
          {[0.8, 1.0, 1.2, 1.5].map((s) => (
            <option key={s} value={s}>
              {s}x 语速
            </option>
          ))}
        </select>
        <button
          className="btn-primary px-3 py-1 text-xs"
          disabled={busy || !selected || !text.trim()}
          onClick={run}
        >
          {busy ? "合成中…" : "▶ 合成试听"}
        </button>
      </div>
      {error && <div className="text-xs text-danger">{error}</div>}
      {audioUrl && (
        <audio className="w-full" controls autoPlay src={audioUrl} />
      )}
    </div>
  );
}

/** 声音中心（F-201~F-204：克隆/试听/绑定 IP/状态轮询） */
export default function VoicesPage() {
  const queryClient = useQueryClient();
  const { current, personas, load } = useIp();

  const { data: voices, refetch } = useQuery({
    queryKey: ["voices"],
    queryFn: () => voiceApi.list(),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((v) => v.status === "training") ? 5000 : false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["voices"] });
    await refetch();
  };

  const boundVoice = voices?.find((v) => v.id === current?.voiceId);
  const ipOf = (v: Voice) => personas.find((p) => p.voiceId === v.id);

  const bindToCurrent = async (v: Voice) => {
    if (!current) return;
    await personaApi.update(current.id, { voiceId: v.id });
    await load();
  };

  // 卡内试听：全局单例 Audio，切换卡片自动停上一段
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  useEffect(() => () => audioRef.current?.pause(), []);

  const togglePlay = (v: Voice) => {
    if (playingId === v.id) {
      audioRef.current?.pause();
      setPlayingId(null);
      return;
    }
    if (!v.sampleUrl) return;
    audioRef.current?.pause();
    const audio = new Audio(v.sampleUrl);
    audio.onended = () => setPlayingId(null);
    void audio.play();
    audioRef.current = audio;
    setPlayingId(v.id);
  };

  return (
    <div className="space-y-5">
      <AssetNav />

      {/* 首屏：当前 IP 默认声音 */}
      <div className="glass flex flex-wrap items-center gap-5 p-5">
        <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-brand-grad text-2xl text-white">
          ♪
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-bold">
              {boundVoice ? boundVoice.name : "未绑定默认声音"}
            </span>
            {boundVoice && (
              <span className="chip border-success/40 text-success">
                默认声音
              </span>
            )}
            {boundVoice && (
              <span className="chip border-info/40 text-info">
                {boundVoice.provider}
              </span>
            )}
          </div>
          <div className="mt-1.5 text-sm text-text-3">
            {boundVoice
              ? `${boundVoice.source === "clone" ? "克隆音色" : "内置音色"} · ${boundVoice.gender} · ${boundVoice.emotion}`
              : `为「${current?.name ?? "当前 IP"}」绑定一个声音，生成链路将自动使用`}
          </div>
        </div>
        <a href="#clone" className="btn-ghost">
          ＋ 克隆新声音
        </a>
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-[1.2fr_1fr]">
        {/* 左列：声音列表 */}
        <div className="glass p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-medium">我的声音（{voices?.length ?? 0}）</h2>
            <span className="text-xs text-text-3">训练中每 5s 自动刷新</span>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {(voices ?? []).map((v) => {
              const ip = ipOf(v);
              const playing = playingId === v.id;
              return (
                <div
                  key={v.id}
                  className={`card-hover rounded-card border p-4 ${
                    current?.voiceId === v.id
                      ? "border-brand-from/60 bg-brand-from/10"
                      : "border-stroke bg-white/[0.03]"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    {/* 试听按钮：渐变圆钮，播放中显示 ■ */}
                    <button
                      aria-label={`试听 ${v.name}`}
                      disabled={!v.sampleUrl || v.status !== "ready"}
                      onClick={() => togglePlay(v)}
                      className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-sm text-white transition-transform hover:scale-105 disabled:opacity-40 ${
                        playing ? "bg-danger/80" : "bg-brand-grad"
                      }`}
                    >
                      {playing ? "■" : "▶"}
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium" title={v.name}>
                        {v.name}
                      </div>
                      <div className="mt-0.5 text-xs text-text-3">
                        {v.source === "clone" ? "克隆音色" : "内置音色"} ·{" "}
                        {v.gender}
                      </div>
                    </div>
                    {v.status === "ready" && (
                      <span className="chip border-success/40 text-[11px] text-success">
                        就绪
                      </span>
                    )}
                    {v.status === "training" && (
                      <span className="chip border-warning/40 text-[11px] text-warning">
                        训练中
                      </span>
                    )}
                    {v.status === "failed" && (
                      <span className="chip border-danger/40 text-[11px] text-danger">
                        失败
                      </span>
                    )}
                  </div>
                  {/* 播放中波形动效 */}
                  {playing && (
                    <div
                      className="mt-3 flex h-5 items-end gap-0.5"
                      aria-hidden
                    >
                      {[
                        0.5, 1, 0.7, 0.9, 0.6, 1, 0.8, 0.5, 0.9, 0.65, 1, 0.7,
                        0.55, 0.85, 0.6, 0.95, 0.7, 0.5,
                      ].map((h, i) => (
                        <span
                          key={i}
                          className="w-1 animate-pulse rounded-full bg-brand-to/70"
                          style={{
                            height: `${h * 100}%`,
                            animationDelay: `${i * 90}ms`,
                          }}
                        />
                      ))}
                    </div>
                  )}
                  <div className="mt-3 flex items-center justify-between">
                    <span className="text-xs text-text-3">
                      {ip ? (
                        <span className="chip text-[11px]">{ip.name}</span>
                      ) : (
                        v.provider
                      )}
                    </span>
                    {v.status === "ready" &&
                      current &&
                      current.voiceId !== v.id && (
                        <button
                          className="btn-ghost px-2.5 py-0.5 text-xs"
                          onClick={() => void bindToCurrent(v)}
                        >
                          设为默认
                        </button>
                      )}
                    {current?.voiceId === v.id && (
                      <span className="text-xs text-success">当前默认</span>
                    )}
                  </div>
                </div>
              );
            })}
            {(voices ?? []).length === 0 && (
              <div className="col-span-full py-10 text-center text-text-3">
                暂无声音，先在右侧克隆一个吧
              </div>
            )}
          </div>
        </div>

        {/* 右列：克隆 + 试听台 */}
        <div className="space-y-4">
          <CloneForm onDone={() => void refresh()} />
          <Playground voices={voices ?? []} defaultVoiceId={boundVoice?.id} />
        </div>
      </div>
    </div>
  );
}
