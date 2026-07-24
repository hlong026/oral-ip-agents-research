import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { adminApi, type ProviderConfig } from "../lib/adminHttp";

const fallbackProviders: ProviderConfig[] = [
  {
    provider: "deepseek",
    displayName: "DeepSeek / LLM",
    enabled: false,
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    priority: 10,
  },
  {
    provider: "dashscope_asr",
    displayName: "DashScope ASR",
    enabled: false,
    baseUrl: "https://dashscope.aliyuncs.com",
    model: "fun-asr",
    priority: 20,
  },
  {
    provider: "hifly",
    displayName: "HiFly 数字人/声音",
    enabled: false,
    baseUrl: "https://hfw-api.hifly.cc",
    model: "",
    priority: 30,
  },
  {
    provider: "douyidou",
    displayName: "Douyidou 视频解析",
    enabled: false,
    baseUrl: "https://gateway.diadi.cn",
    model: "",
    priority: 40,
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
          密钥由管理员维护；用户端只消费业务能力，不接触供应商凭据。
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
                  {provider.apiKeyConfigured ? "密钥已配置" : "密钥未配置"}
                </span>
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
            <Field
              label="Base URL"
              value={provider.baseUrl}
              onChange={(baseUrl) => update(index, { baseUrl })}
            />
            {provider.provider === "douyidou" && (
              <Field
                label="App ID"
                value={provider.appId || ""}
                onChange={(appId) => update(index, { appId })}
              />
            )}
            <Field
              label="模型"
              value={provider.model || ""}
              onChange={(model) => update(index, { model })}
            />
            <Field
              label={
                provider.provider === "douyidou"
                  ? provider.apiKeyConfigured
                    ? "App Secret（已配置，留空不覆盖）"
                    : "App Secret"
                  : provider.apiKeyConfigured
                    ? "API Key（已配置，留空不覆盖）"
                    : "API Key"
              }
              type="password"
              value={provider.apiKey || ""}
              onChange={(apiKey) => update(index, { apiKey })}
            />
            <label className="block">
              <span className="label">优先级</span>
              <input
                className="input"
                type="number"
                value={provider.priority || 0}
                onChange={(event) =>
                  update(index, { priority: Number(event.target.value) })
                }
              />
            </label>
            <button
              className="btn-primary"
              disabled={save.isPending}
              onClick={() => save.mutate(provider)}
            >
              保存配置
            </button>
          </section>
        ))}
      </div>
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
