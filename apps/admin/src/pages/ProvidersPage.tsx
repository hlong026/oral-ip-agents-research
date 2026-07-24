import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  adminApi,
  type ProviderConfig,
  type ProviderProbeResult,
} from "../lib/adminHttp";

const fallbackProviders: ProviderConfig[] = [
  {
    provider: "deepseek",
    displayName: "DeepSeek / LLM",
    enabled: false,
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
  },
  {
    provider: "dashscope_asr",
    displayName: "DashScope ASR",
    enabled: false,
    baseUrl: "https://dashscope.aliyuncs.com",
    model: "fun-asr",
  },
  {
    provider: "hifly",
    displayName: "HiFly 数字人/声音",
    enabled: false,
    baseUrl: "https://hfw-api.hifly.cc",
    model: "",
  },
  {
    provider: "douyidou",
    displayName: "Douyidou 视频解析",
    enabled: false,
    baseUrl: "https://gateway.diadi.cn",
    model: "",
  },
];

export default function ProvidersPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-providers"],
    queryFn: adminApi.listProviders,
  });
  const [items, setItems] = useState(fallbackProviders);
  const [message, setMessage] = useState("");
  const [probeResults, setProbeResults] = useState<
    Record<string, ProviderProbeResult>
  >({});

  useEffect(() => {
    if (data && data.length > 0) setItems(data);
  }, [data]);

  const save = useMutation({
    mutationFn: (provider: ProviderConfig) =>
      adminApi.saveProvider(provider.provider, provider),
    onSuccess: async () => {
      setMessage("Provider 配置已保存");
      await queryClient.invalidateQueries({ queryKey: ["admin-providers"] });
    },
  });
  const probe = useMutation({
    mutationFn: adminApi.probeProvider,
    onSuccess: (result) => {
      setProbeResults((current) => ({
        ...current,
        [result.provider]: result,
      }));
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
      <div>
        <h1 className="text-2xl font-semibold">Provider 配置</h1>
        <p className="mt-2 text-sm text-text-3">
          密钥会加密保存在本地数据库；用户端只消费业务能力，不接触供应商凭据。
        </p>
      </div>
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
                <h2 className="font-semibold">{provider.displayName}</h2>
                <p className="mt-1 text-xs text-text-3">{provider.provider}</p>
                <span className="chip mt-2">
                  {provider.configured ? "配置完整" : "配置不完整"}
                </span>
                {provider.missingFields &&
                  provider.missingFields.length > 0 && (
                    <p className="mt-2 text-xs text-warning">
                      缺少：{provider.missingFields.join("、")}
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
                label="Base URL"
                value={provider.baseUrl}
                onChange={(baseUrl) => update(index, { baseUrl })}
              />
            )}
            {provider.provider === "douyidou" && (
              <Field
                label="App ID"
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
              label={
                provider.provider === "douyidou" ? "App Secret" : "API Key"
              }
              value={provider.apiKey || ""}
              configured={Boolean(provider.apiKeyConfigured)}
              onChange={(apiKey) => update(index, { apiKey })}
            />
            {provider.provider === "dashscope_asr" && (
              <>
                <Field
                  label="Workspace ID（可选）"
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
              {provider.probeMode === "sample" ? "检查配置" : "测试连接"}
            </button>
            {probeResults[provider.provider]?.message && (
              <p className="text-sm text-text-2">
                {probeResults[provider.provider]?.message}
              </p>
            )}
          </section>
        ))}
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
