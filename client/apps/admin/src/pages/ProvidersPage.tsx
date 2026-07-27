import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RefreshCw, TriangleAlert, X } from "lucide-react";
import { useEffect, useState } from "react";
import {
  adminApi,
  type ProviderConfig,
  type ProviderProbeResult,
  type ProviderReadiness,
} from "@oral/admin-api-client";

const fallbackProviders: ProviderConfig[] = [
  {
    provider: "deepseek",
    displayName: "大模型服务",
    enabled: false,
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
  },
  {
    provider: "dashscope_asr",
    displayName: "语音识别服务",
    enabled: false,
    baseUrl: "https://dashscope.aliyuncs.com",
    model: "fun-asr",
  },
  {
    provider: "hifly",
    displayName: "数字人和声音服务",
    enabled: false,
    baseUrl: "https://hfw-api.hifly.cc",
    model: "",
  },
  {
    provider: "douyidou",
    displayName: "视频解析服务",
    enabled: false,
    baseUrl: "https://gateway.diadi.cn",
    model: "",
  },
];

const providerNames: Record<string, string> = {
  deepseek: "大模型服务",
  dashscope_asr: "语音识别服务",
  hifly: "数字人和声音服务",
  douyidou: "视频解析服务",
};

const missingFieldNames: Record<string, string> = {
  "API Key": "接口密钥",
  "App ID": "应用编号",
  "App Secret": "应用密钥",
  "Base URL": "服务地址",
  "Workspace ID": "工作空间编号",
};

const environmentNames: Record<string, string> = {
  dev: "开发环境",
  test: "测试环境",
  production: "生产环境",
};

const chainNames: Record<string, string> = {
  llm: "大模型",
  parse: "视频解析",
  asr: "语音识别",
  voice: "声音生成",
  avatar: "数字人",
  compose: "视频合成",
  publish: "发布",
};

const runtimeProviderNames: Record<string, string> = {
  "deepseek-v3": "深度求索大模型",
  douyidou: "视频解析服务",
  "aliyun-fun-asr": "阿里云语音识别",
  "hifly-voice": "飞影声音服务",
  "hifly-avatar": "飞影数字人服务",
  "ffmpeg-local": "本地视频合成",
  "third-party-parse": "第三方视频解析",
  "sau-douyin": "抖音发布服务",
  "sau-xiaohongshu": "小红书发布服务",
  "sau-tencent": "视频号发布服务",
  "mock-llm": "模拟大模型",
  "mock-parse": "模拟视频解析",
  "mock-faster-whisper": "模拟语音识别",
  "mock-voice": "模拟声音服务",
  "mock-avatar": "模拟数字人服务",
  "mock-ffmpeg": "模拟视频合成",
};

function providerName(provider: string, fallback?: string) {
  return providerNames[provider] ?? fallback ?? "未命名服务";
}

function formatMissingFields(fields: string[]) {
  return fields.map((field) => missingFieldNames[field] ?? field).join("、");
}

type ProbeFeedback = {
  providerName: string;
  title: string;
  message: string;
  tone: "success" | "warning" | "error";
};

export default function ProvidersPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-providers"],
    queryFn: adminApi.listProviders,
  });
  const [items, setItems] = useState(fallbackProviders);
  const [message, setMessage] = useState("");
  const [probeFeedback, setProbeFeedback] = useState<ProbeFeedback | null>(
    null,
  );

  useEffect(() => {
    if (data && data.length > 0) setItems(data);
  }, [data]);

  const save = useMutation({
    mutationFn: (provider: ProviderConfig) =>
      adminApi.saveProvider(provider.provider, provider),
    onSuccess: async () => {
      setMessage("服务商配置已保存");
      await queryClient.invalidateQueries({ queryKey: ["admin-providers"] });
    },
  });
  const probe = useMutation({
    mutationFn: adminApi.probeProvider,
    onSuccess: (result) => {
      const item = items.find(
        (candidate) => candidate.provider === result.provider,
      );
      const presentation = probePresentation(result);
      setProbeFeedback({
        providerName: providerName(result.provider, item?.displayName),
        message: result.message,
        ...presentation,
      });
    },
    onError: (probeError, provider) => {
      const item = items.find((candidate) => candidate.provider === provider);
      setProbeFeedback({
        providerName: providerName(provider, item?.displayName),
        title: "连接测试失败",
        message:
          probeError instanceof Error ? probeError.message : "连接测试失败",
        tone: "error",
      });
    },
  });

  function update(index: number, patch: Partial<ProviderConfig>) {
    setItems((providers) =>
      providers.map((provider, i) =>
        i === index ? { ...provider, ...patch } : provider,
      ),
    );
  }

  return (
    <div className="space-y-5">
      {probeFeedback && (
        <ProbeToast
          feedback={probeFeedback}
          onClose={() => setProbeFeedback(null)}
        />
      )}
      <div>
        <h1 className="text-2xl font-semibold">服务商配置</h1>
        <p className="mt-2 text-sm text-text-3">
          密钥会加密保存在本地数据库；用户端只消费业务能力，不接触供应商凭据。
        </p>
      </div>
      <ReadinessBoard />
      {isLoading && <p className="text-sm text-text-3">加载中...</p>}
      {(error instanceof Error || save.error instanceof Error || message) && (
        <p className="text-sm text-text-2">
          {error instanceof Error
            ? error.message
            : save.error instanceof Error
              ? save.error.message
              : message}
        </p>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        {items.map((provider, index) => (
          <section key={provider.provider} className="glass space-y-4 p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">
                  {providerName(provider.provider, provider.displayName)}
                </h2>
                <span className="chip mt-2">
                  {provider.configured ? "配置完整" : "配置不完整"}
                </span>
                {provider.missingFields &&
                  provider.missingFields.length > 0 && (
                    <p className="mt-2 text-xs text-warning">
                      缺少：{formatMissingFields(provider.missingFields)}
                    </p>
                  )}
              </div>
              <label className="flex items-center gap-2 text-sm text-text-2">
                <input
                  type="checkbox"
                  checked={provider.enabled}
                  onChange={(event) =>
                    update(index, { enabled: event.target.checked })
                  }
                />
                启用
              </label>
            </div>
            {provider.provider !== "dashscope_asr" && (
              <Field
                label="服务地址"
                value={provider.baseUrl}
                onChange={(baseUrl) => update(index, { baseUrl })}
              />
            )}
            {provider.provider === "douyidou" && (
              <Field
                label="应用编号"
                value={provider.appId || ""}
                onChange={(appId) => update(index, { appId })}
              />
            )}
            {provider.provider === "deepseek" && (
              <Field
                label="模型"
                value={provider.model || ""}
                onChange={(model) => update(index, { model })}
              />
            )}
            <SecretField
              label={provider.provider === "douyidou" ? "应用密钥" : "接口密钥"}
              value={provider.apiKey || ""}
              configured={Boolean(provider.apiKeyConfigured)}
              onChange={(apiKey) => update(index, { apiKey })}
            />
            {provider.provider === "dashscope_asr" && (
              <>
                <Field
                  label="工作空间编号（可选）"
                  value={provider.workspaceId || ""}
                  onChange={(workspaceId) => update(index, { workspaceId })}
                />
                <SelectField
                  label="地域"
                  value={provider.region || "cn-beijing"}
                  options={[
                    { value: "cn-beijing", label: "中国内地（北京）" },
                    {
                      value: "ap-southeast-1",
                      label: "国际（新加坡）",
                    },
                  ]}
                  onChange={(region) => update(index, { region })}
                />
                <Field
                  label="异步模型"
                  value={provider.model || ""}
                  onChange={(model) => update(index, { model })}
                />
                <Field
                  label="短音频同步模型"
                  value={provider.flashModel || ""}
                  onChange={(flashModel) => update(index, { flashModel })}
                />
                <Field
                  label="同步分流阈值（秒）"
                  type="number"
                  value={String(provider.flashThresholdSec || 300)}
                  onChange={(value) =>
                    update(index, { flashThresholdSec: Number(value) })
                  }
                />
              </>
            )}
            <button
              className="btn-primary"
              disabled={save.isPending}
              onClick={() => save.mutate(provider)}
            >
              保存配置
            </button>
            <button
              className="btn-ghost ml-2"
              disabled={
                probe.isPending && probe.variables === provider.provider
              }
              onClick={() => probe.mutate(provider.provider)}
            >
              {probe.isPending && probe.variables === provider.provider
                ? "测试中..."
                : provider.probeMode === "sample"
                  ? "检查配置"
                  : "测试连接"}
            </button>
          </section>
        ))}
      </div>
    </div>
  );
}

function ReadinessBoard() {
  const [withProbe, setWithProbe] = useState(false);
  const { data, isLoading, isFetching, refetch } = useQuery<ProviderReadiness>({
    queryKey: ["provider-readiness", withProbe],
    queryFn: () => adminApi.providerReadiness(withProbe),
  });

  if (isLoading) {
    return (
      <section className="glass p-5">
        <p className="text-sm text-text-3">就绪度检测中...</p>
      </section>
    );
  }
  // 后端升级中或代理返回旧结构时，不让辅助看板拖垮服务商配置主功能。
  if (!data || !Array.isArray(data.items)) return null;

  const mockLeaked = data.providerMode === "mock_fallback";
  const providerChains = data.providerChains ?? {};
  return (
    <section className="glass space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">供应商就绪度看板</h2>
          <p className="mt-1 text-xs text-text-3">
            切生产前逐项核对：Key 已配置、开关已打开、连通性探测通过。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-text-2">
            <input
              type="checkbox"
              checked={withProbe}
              onChange={(event) => setWithProbe(event.target.checked)}
            />
            含连通性探测
          </label>
          <button
            type="button"
            className="btn-ghost"
            disabled={isFetching}
            onClick={() => refetch()}
          >
            <RefreshCw
              className={`mr-1 inline h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`}
            />
            刷新
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="chip">
          环境：{environmentNames[data.env] ?? "未知环境"}
        </span>
        <span
          className={`chip ${mockLeaked ? "border-warning/60 text-warning" : "border-success/60 text-success"}`}
        >
          服务商模式：
          {mockLeaked ? "含模拟降级（仅限开发/测试）" : "全真实链路"}
        </span>
        <span
          className={`chip ${data.allReady ? "border-success/60 text-success" : "border-warning/60 text-warning"}`}
        >
          {data.allReady ? "全部就绪" : "存在未就绪项"}
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {data.items.map((item) => (
          <div
            key={item.provider}
            className={`rounded-xl border p-3 ${
              item.ready
                ? "border-success/40 bg-success/5"
                : "border-warning/40 bg-warning/5"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">
                {providerName(item.provider)}
              </span>
              {item.ready ? (
                <Check className="h-4 w-4 text-success" />
              ) : (
                <TriangleAlert className="h-4 w-4 text-warning" />
              )}
            </div>
            <ul className="mt-2 space-y-1 text-xs text-text-2">
              <li>开关：{item.enabled ? "已启用" : "未启用"}</li>
              <li>
                配置：
                {item.configured
                  ? "完整"
                  : `缺少 ${formatMissingFields(item.missingFields)}`}
              </li>
              {item.probeStatus && (
                <li>
                  探测：
                  {item.probeStatus === "verified" ? "通过" : item.probeMessage}
                </li>
              )}
            </ul>
          </div>
        ))}
      </div>
      <details className="text-xs text-text-3">
        <summary className="cursor-pointer">运行时降级链名单</summary>
        <ul className="mt-2 space-y-1">
          {Object.entries(providerChains).map(([kind, names]) => (
            <li key={kind}>
              <span className="font-medium">
                {chainNames[kind] ?? "其他服务"}
              </span>
              ：
              {names
                .map((name) => runtimeProviderNames[name] ?? "未命名服务")
                .join(" → ")}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function probePresentation(
  result: ProviderProbeResult,
): Pick<ProbeFeedback, "title" | "tone"> {
  if (result.status === "verified") {
    return { title: "连接测试成功", tone: "success" };
  }
  if (result.status === "needs_sample") {
    return { title: "需要真实样例", tone: "warning" };
  }
  if (result.status === "incomplete") {
    return { title: "配置不完整", tone: "warning" };
  }
  return { title: "连接测试失败", tone: "error" };
}

function ProbeToast({
  feedback,
  onClose,
}: {
  feedback: ProbeFeedback;
  onClose: () => void;
}) {
  const toneClass =
    feedback.tone === "success"
      ? "border-success/50 bg-success/10"
      : feedback.tone === "warning"
        ? "border-warning/50 bg-warning/10"
        : "border-danger/50 bg-danger/10";
  const Icon =
    feedback.tone === "success"
      ? Check
      : feedback.tone === "warning"
        ? TriangleAlert
        : X;

  return (
    <div
      role={feedback.tone === "error" ? "alert" : "status"}
      aria-label={`${feedback.providerName}${feedback.title}`}
      className={`fixed right-6 top-6 z-50 w-[min(26rem,calc(100vw-3rem))] rounded-2xl border p-4 shadow-2xl backdrop-blur-xl ${toneClass}`}
    >
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-current">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">
            {feedback.providerName} · {feedback.title}
          </p>
          <p className="mt-1 text-sm text-text-2">{feedback.message}</p>
        </div>
        <button
          type="button"
          aria-label="关闭连接测试提示"
          className="text-text-3 hover:text-text-1"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function SecretField({
  label,
  value,
  configured,
  onChange,
}: {
  label: string;
  value: string;
  configured: boolean;
  onChange: (value: string) => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const accessibleLabel = configured
    ? `${label}（已保存，输入新密钥可替换）`
    : label;

  return (
    <div>
      <label className="block">
        <span className="label">{accessibleLabel}</span>
        <div className="flex gap-2">
          <input
            className="input"
            type={revealed ? "text" : "password"}
            value={value}
            placeholder={configured ? "••••••••••••••••" : undefined}
            autoComplete="new-password"
            onChange={(event) => onChange(event.target.value)}
          />
          <button
            type="button"
            className="btn-ghost shrink-0"
            disabled={!value}
            onClick={() => setRevealed((current) => !current)}
          >
            {revealed ? "隐藏密钥" : "显示密钥"}
          </button>
        </div>
      </label>
      {configured && !value && (
        <p className="mt-2 text-xs text-success">
          密钥已安全保存，服务端不会回传明文。
        </p>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <input
        className="input"
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <select
        className="input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
