import { HttpError, personaApi, voiceApi } from "@oral/api-client";
import { useIp } from "@oral/stores";
import type { Voice } from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic, Music, Play, Square, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AssetNav from "../components/AssetNav";
import {
  confirmMeteredOperation,
  mediaDurationSeconds,
  textOperationUsage,
} from "../lib/meteredOperation";

// 飞影声音克隆素材约束：mp3/m4a/wav，≤20MB，5 秒～3 分钟
const SAMPLE_MAX_BYTES = 20 * 1024 * 1024;
const SAMPLE_MIN_SECONDS = 5;
const SAMPLE_MAX_SECONDS = 180;

/** 克隆新声音表单（录音优先，上传为可选；合规红线：强制 consent 授权勾选） */
function CloneForm({
  onDone,
  startSignal = 0,
}: {
  onDone: () => void;
  startSignal?: number;
}) {
  const [name, setName] = useState("");
  const [consent, setConsent] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  // 录音优先：默认现场录制声音样本，上传音频仅作为可选入口
  const [mode, setMode] = useState<"record" | "upload">("record");
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [previewUrl, setPreviewUrl] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const timerRef = useRef<number | null>(null);

  // 卸载时释放麦克风与预听 URL
  useEffect(
    () => () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      recorderRef.current?.stream.getTracks().forEach((t) => t.stop());
    },
    [],
  );
  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  const startRecording = async () => {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      // 供应商仅支持 mp3/m4a/wav：优先录制 audio/mp4（m4a），webm 仅作兜底（后端会转码）
      const preferred = MediaRecorder.isTypeSupported("audio/mp4")
        ? "audio/mp4"
        : undefined;
      const rec = new MediaRecorder(
        stream,
        preferred ? { mimeType: preferred } : undefined,
      );
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const type = rec.mimeType || "audio/webm";
        const blob = new Blob(chunks, { type });
        const ext = type.includes("mp4") ? "m4a" : "webm";
        setFile(new File([blob], `录音样本-${Date.now()}.${ext}`, { type }));
        setPreviewUrl(URL.createObjectURL(blob));
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
      setSeconds(0);
      timerRef.current = window.setInterval(
        () => setSeconds((s) => s + 1),
        1000,
      );
    } catch {
      setError("无法访问麦克风，请检查浏览器授权，或改为上传音频文件");
    }
  };

  const stopRecording = () => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    recorderRef.current?.stop();
    setRecording(false);
  };

  // 录音时长约束：不足 5 秒提示重录，满 3 分钟自动停止
  useEffect(() => {
    if (!recording) return;
    if (seconds >= SAMPLE_MAX_SECONDS) stopRecording();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seconds, recording]);

  const fmt = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  // 顶部「克隆新声音」点击后直接拉起录音（属于用户手势，可触发麦克风授权）
  useEffect(() => {
    if (!startSignal) return;
    setMode("record");
    if (!recorderRef.current || recorderRef.current.state !== "recording") {
      void startRecording();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startSignal]);

  const submit = async () => {
    if (!file || !consent || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      // 提交前兼容校验：大小与时长不达标时直接拦截，避免白扣积分
      if (file.size > SAMPLE_MAX_BYTES)
        throw new Error("声音样本超过 20MB，请压缩或剪短后重试");
      const sampleSeconds = await mediaDurationSeconds(file).catch(() => null);
      if (
        sampleSeconds !== null &&
        (sampleSeconds < SAMPLE_MIN_SECONDS ||
          sampleSeconds > SAMPLE_MAX_SECONDS)
      )
        throw new Error("声音样本时长需在 5 秒～3 分钟之间");
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
      setPreviewUrl("");
      onDone();
    } catch (e) {
      setError(
        e instanceof HttpError
          ? e.body.message
          : e instanceof Error && e.message
            ? e.message
            : "克隆发起失败，请重试",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="glass-strong space-y-3 p-5" id="clone">
      <h2 className="font-medium">克隆一个新声音</h2>
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
        <div className="flex items-center justify-between">
          <label className="label">声音样本（5 秒～3 分钟清晰人声）</label>
          <button
            className="text-xs text-brand-to hover:underline"
            onClick={() => {
              if (recording) stopRecording();
              setMode((m) => (m === "record" ? "upload" : "record"));
            }}
          >
            {mode === "record" ? "改为上传音频（可选）" : "改为现场录音"}
          </button>
        </div>
        {mode === "record" ? (
          <div className="space-y-2">
            {recording ? (
              // 录音中：长条区域整体可点击停止
              <button
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-danger/40 bg-danger/10 py-6 text-sm text-danger transition-colors hover:bg-danger/15"
                onClick={stopRecording}
              >
                <span className="h-2 w-2 animate-pulse rounded-full bg-danger" />
                录音中 {fmt(seconds)}
                <Square className="ml-1 h-3.5 w-3.5" /> 点击停止
              </button>
            ) : (
              // 未录音：与上传区同款长条形虚线区域，图标 + 提示文字
              <button
                className="btn-ghost flex w-full items-center justify-center gap-1.5 border-dashed py-6 text-text-3"
                onClick={() => void startRecording()}
              >
                <Mic className="h-4 w-4" />
                {file && previewUrl ? "点击重新录制" : "点击开始录音"}
              </button>
            )}
            {previewUrl && !recording && (
              <audio className="w-full" controls src={previewUrl} />
            )}
          </div>
        ) : (
          <>
            <button
              className="btn-ghost flex w-full items-center justify-center gap-1.5 border-dashed py-6 text-text-3"
              onClick={() => fileRef.current?.click()}
            >
              {file ? (
                `已选择：${file.name}`
              ) : (
                <>
                  <Upload className="h-4 w-4" /> 点击选择音频文件（WAV/MP3）
                </>
              )}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="audio/*,.wav,.mp3,.m4a"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </>
        )}
      </div>
      <label className="flex cursor-pointer items-start gap-2 rounded-xl border border-info/30 bg-info/10 p-3 text-xs text-info">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
        />
        <span>我确认拥有该声音的合法授权</span>
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
  const [text, setText] = useState(
    "我是李老师，做财税 12 年，今天不绕弯子，三分钟给你讲透老板们最容易踩的那个税务坑。",
  );
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
      setError(
        e instanceof HttpError
          ? e.body.message
          : e instanceof Error && e.message
            ? e.message
            : "合成失败，请重试",
      );
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
          className="btn-primary flex items-center gap-1 px-3 py-1 text-xs"
          disabled={busy || !selected || !text.trim()}
          onClick={run}
        >
          {busy ? (
            "合成中…"
          ) : (
            <>
              <Play className="h-3 w-3" /> 合成试听
            </>
          )}
        </button>
      </div>
      {error && <div className="text-xs text-danger">{error}</div>}
      {audioUrl && (
        <audio className="w-full" controls autoPlay src={audioUrl} />
      )}
    </div>
  );
}

/** 需要继续轮询状态接口的声音：训练中，或待确认但试听样音尚未就绪（后端会自愈补存） */
const needsStatusPoll = (v: Voice) =>
  v.status === "training" || (v.status === "pending_confirm" && !v.demoUrl);

/** 声音中心（F-201~F-204：克隆/试听/绑定 IP/状态轮询） */
export default function VoicesPage() {
  const queryClient = useQueryClient();
  const { current, personas, load } = useIp();
  const [actionId, setActionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");

  const { data: voices, refetch } = useQuery({
    queryKey: ["voices"],
    queryFn: async () => {
      const listed = await voiceApi.list();
      const updates = await Promise.all(
        listed.filter(needsStatusPoll).map((voice) => voiceApi.status(voice.id)),
      );
      const byId = new Map(updates.map((voice) => [voice.id, voice]));
      return listed.map((voice) => {
        const polled = byId.get(voice.id);
        if (!polled) return voice;
        // 状态接口的 demoUrl 可能比列表新（自愈补存），但为空时不覆盖列表值
        return {
          ...voice,
          status: polled.status,
          demoUrl: polled.demoUrl ?? voice.demoUrl,
        };
      });
    },
    refetchInterval: (q) =>
      (q.state.data ?? []).some(needsStatusPoll) ? 5000 : false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["voices"] });
    await refetch();
  };

  const boundVoice = voices?.find((v) => v.id === current?.voiceId);
  const ipOf = (v: Voice) => personas.find((p) => p.voiceId === v.id);
  // 顶部 CTA → 克隆表单自动开始录音的信号
  const [recordSignal, setRecordSignal] = useState(0);

  const bindToCurrent = async (v: Voice) => {
    if (!current) return;
    await personaApi.update(current.id, { voiceId: v.id });
    await load();
  };

  const finishConfirmation = async (
    voice: Voice,
    action: "confirm" | "reject",
  ) => {
    setActionId(voice.id);
    setActionError("");
    try {
      const updated = await voiceApi[action](voice.id);
      queryClient.setQueryData<Voice[]>(["voices"], (currentVoices = []) =>
        currentVoices.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (error) {
      setActionError(
        error instanceof HttpError ? error.body.message : "操作失败，请重试",
      );
    } finally {
      setActionId(null);
    }
  };

  // 删除二次确认：首次点击变为「确认删除？」，再次点击才执行
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const removeVoice = async (v: Voice) => {
    if (pendingDeleteId !== v.id) {
      setPendingDeleteId(v.id);
      return;
    }
    setActionId(v.id);
    setActionError("");
    try {
      await voiceApi.remove(v.id);
      setPendingDeleteId(null);
      // 后端已自动解绑引用该声音的 IP，刷新 persona 状态
      if (ipOf(v)) await load();
      await refresh();
    } catch (error) {
      setActionError(
        error instanceof HttpError ? error.body.message : "删除失败，请重试",
      );
    } finally {
      setActionId(null);
    }
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
        <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-brand-grad text-white">
          <Music className="h-7 w-7" />
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
          </div>
          <div className="mt-1.5 text-sm text-text-3">
            {boundVoice
              ? [
                  boundVoice.source === "clone" ? "克隆音色" : "内置音色",
                  boundVoice.gender,
                  boundVoice.emotion,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : `为「${current?.name ?? "当前 IP"}」绑定一个声音，生成链路将自动使用`}
          </div>
        </div>
        <button
          className="btn-ghost"
          onClick={() => {
            document
              .getElementById("clone")
              ?.scrollIntoView({ behavior: "smooth", block: "start" });
            setRecordSignal((s) => s + 1);
          }}
        >
          ＋ 克隆新声音
        </button>
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
                    {/* 试听按钮：渐变圆钮，播放中显示停止图标 */}
                    <button
                      aria-label={`试听 ${v.name}`}
                      disabled={!v.sampleUrl || v.status !== "ready"}
                      onClick={() => togglePlay(v)}
                      className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-white transition-transform hover:scale-105 disabled:opacity-40 ${
                        playing ? "bg-danger/80" : "bg-brand-grad"
                      }`}
                    >
                      {playing ? (
                        <Square className="h-4 w-4" />
                      ) : (
                        <Play className="h-4 w-4" />
                      )}
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium" title={v.name}>
                        {v.name}
                      </div>
                      <div className="mt-0.5 text-xs text-text-3">
                        {[
                          v.source === "clone" ? "克隆音色" : "内置音色",
                          v.gender,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
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
                    {v.status === "pending_confirm" && (
                      <span className="chip border-info/40 text-[11px] text-info">
                        待试听确认
                      </span>
                    )}
                    {v.status === "rejected" && (
                      <span className="chip border-stroke text-[11px] text-text-3">
                        已拒绝
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
                  {v.status === "pending_confirm" && v.demoUrl && (
                    <div className="mt-3 space-y-2 rounded-xl border border-info/20 bg-info/5 p-3">
                      <audio className="w-full" controls src={v.demoUrl} />
                      <div className="flex justify-end gap-2">
                        <button
                          className="btn-ghost px-3 py-1 text-xs text-danger"
                          disabled={actionId === v.id}
                          onClick={() => void finishConfirmation(v, "reject")}
                        >
                          拒绝结果
                        </button>
                        <button
                          className="btn-primary px-3 py-1 text-xs"
                          disabled={actionId === v.id}
                          onClick={() => void finishConfirmation(v, "confirm")}
                        >
                          确认使用
                        </button>
                      </div>
                    </div>
                  )}
                  {v.status === "pending_confirm" && !v.demoUrl && (
                    <div className="mt-3 flex items-center gap-2 rounded-xl border border-info/20 bg-info/5 p-3 text-xs text-text-3">
                      <span className="h-2 w-2 animate-pulse rounded-full bg-info" />
                      试听样音生成中，就绪后自动刷新…
                    </div>
                  )}
                  <div className="mt-3 flex items-center justify-between">
                    <span className="text-xs text-text-3">
                      {ip ? (
                        <span className="chip text-[11px]">{ip.name}</span>
                      ) : (
                        "暂未绑定 IP"
                      )}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {v.status === "ready" && (
                        <Link
                          className="btn-ghost px-2.5 py-0.5 text-xs text-brand-to"
                          to={`/create?voiceId=${v.id}`}
                        >
                          去成片
                        </Link>
                      )}
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
                      <button
                        aria-label={`删除 ${v.name}`}
                        className={`btn-ghost px-2 py-0.5 text-xs ${
                          pendingDeleteId === v.id
                            ? "text-danger"
                            : "text-text-3 hover:text-danger"
                        }`}
                        disabled={actionId === v.id}
                        onClick={() => void removeVoice(v)}
                      >
                        {pendingDeleteId === v.id ? (
                          "确认删除？"
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
            {(voices ?? []).length === 0 && (
              <div className="col-span-full py-10 text-center text-text-3">
                暂无声音，先在右侧克隆一个吧
              </div>
            )}
            {actionError && (
              <div className="col-span-full text-sm text-danger">
                {actionError}
              </div>
            )}
          </div>
        </div>

        {/* 右列：克隆 + 试听台 */}
        <div className="space-y-4">
          <CloneForm onDone={() => void refresh()} startSignal={recordSignal} />
          <Playground voices={voices ?? []} defaultVoiceId={boundVoice?.id} />
        </div>
      </div>
    </div>
  );
}
