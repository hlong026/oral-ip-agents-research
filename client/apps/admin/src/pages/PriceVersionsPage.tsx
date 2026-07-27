import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { adminApi, type ModulePrice } from "@oral/admin-api-client";

const defaultModules: ModulePrice[] = [
  {
    module: "topic_generation",
    displayName: "AI 选题生成",
    billingUnit: "per_action",
    unitSize: 1,
    pointsPerUnit: 2,
    minimumPoints: 2,
    enabled: true,
    publicDescription: "每次 2 积分",
    internalCostCentsPerUnit: 10,
    targetMarginBps: 6000,
  },
  {
    module: "script_generation",
    displayName: "AI 文案脚本",
    billingUnit: "per_1k_tokens",
    unitSize: 1000,
    pointsPerUnit: 6,
    minimumPoints: 6,
    enabled: true,
    publicDescription: "每 1000 Token 6 积分",
    internalCostCentsPerUnit: 30,
    targetMarginBps: 6000,
  },
  {
    module: "asr",
    displayName: "ASR 音频转文字",
    billingUnit: "per_minute",
    unitSize: 60,
    pointsPerUnit: 3,
    minimumPoints: 3,
    enabled: true,
    publicDescription: "每分钟 3 积分",
    internalCostCentsPerUnit: 20,
    targetMarginBps: 6000,
  },
  {
    module: "tts",
    displayName: "TTS 文本生成语音",
    billingUnit: "per_1k_chars",
    unitSize: 1000,
    pointsPerUnit: 10,
    minimumPoints: 10,
    enabled: true,
    publicDescription: "每 1000 字 10 积分",
    internalCostCentsPerUnit: 250,
    targetMarginBps: 6000,
  },
  {
    module: "voice_clone",
    displayName: "声音克隆 / 训练",
    billingUnit: "per_asset",
    unitSize: 1,
    pointsPerUnit: 0,
    minimumPoints: 0,
    enabled: false,
    publicDescription: "按每个训练资产计费",
    internalCostCentsPerUnit: 0,
    targetMarginBps: 6000,
  },
  {
    module: "digital_human",
    displayName: "数字人视频",
    billingUnit: "per_second",
    unitSize: 1,
    pointsPerUnit: 2,
    minimumPoints: 2,
    enabled: true,
    publicDescription: "每秒 2 积分",
    internalCostCentsPerUnit: 20,
    targetMarginBps: 6000,
  },
  {
    module: "image_generation",
    displayName: "图片生成",
    billingUnit: "per_image",
    unitSize: 1,
    pointsPerUnit: 8,
    minimumPoints: 8,
    enabled: true,
    publicDescription: "每张 8 积分",
    internalCostCentsPerUnit: 120,
    targetMarginBps: 6000,
  },
  {
    module: "video_generation",
    displayName: "AI 视频素材生成",
    billingUnit: "per_second",
    unitSize: 1,
    pointsPerUnit: 0,
    minimumPoints: 0,
    enabled: false,
    publicDescription: "按生成时长计费",
    internalCostCentsPerUnit: 0,
    targetMarginBps: 6000,
  },
  {
    module: "video_translation",
    displayName: "视频翻译 / 口型同步",
    billingUnit: "per_second",
    unitSize: 1,
    pointsPerUnit: 0,
    minimumPoints: 0,
    enabled: false,
    publicDescription: "按处理时长计费",
    internalCostCentsPerUnit: 0,
    targetMarginBps: 6000,
  },
  {
    module: "hd_export",
    displayName: "高清导出",
    billingUnit: "per_action",
    unitSize: 1,
    pointsPerUnit: 3,
    minimumPoints: 3,
    enabled: true,
    publicDescription: "每次高清导出 3 积分",
    internalCostCentsPerUnit: 0,
    targetMarginBps: 6000,
  },
];

const moduleBillingUnits: Record<string, string[]> = {
  topic_generation: ["per_action", "per_1k_chars", "per_1k_tokens"],
  script_generation: ["per_action", "per_1k_chars", "per_1k_tokens"],
  asr: ["per_action", "per_minute", "per_second"],
  tts: ["per_action", "per_1k_chars", "per_1k_tokens"],
  voice_clone: ["per_action", "per_asset"],
  digital_human: ["per_action", "per_minute", "per_second", "per_asset"],
  image_generation: ["per_action", "per_image"],
  video_generation: ["per_action", "per_minute", "per_second", "per_asset"],
  video_translation: ["per_action", "per_minute", "per_second"],
  hd_export: ["per_action", "per_asset"],
};

export default function PriceVersionsPage() {
  const queryClient = useQueryClient();
  const [version, setVersion] = useState(
    `price-${new Date().toISOString().slice(0, 10)}`,
  );
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [modulePrices, setModulePrices] = useState(defaultModules);
  const [message, setMessage] = useState("");
  const [effectiveAt, setEffectiveAt] = useState("");
  const {
    data = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["admin-price-versions"],
    queryFn: adminApi.listPriceVersions,
  });
  const selected = useMemo(
    () => data.find((item) => item.id === selectedVersionId),
    [data, selectedVersionId],
  );
  const selectedModules = useQuery({
    queryKey: ["admin-price-modules", selectedVersionId],
    queryFn: () => adminApi.listModulePrices(selectedVersionId),
    enabled: Boolean(selectedVersionId),
  });

  useEffect(() => {
    if (selectedModules.data?.length) {
      setModulePrices(
        defaultModules.map(
          (definition) =>
            selectedModules.data.find(
              (item) => item.module === definition.module,
            ) || definition,
        ),
      );
    } else if (selectedVersionId && selectedModules.data) {
      setModulePrices(defaultModules);
    }
  }, [selectedModules.data, selectedVersionId]);

  const createVersion = useMutation({
    mutationFn: () => adminApi.createPriceVersion(version),
    onSuccess: async (created) => {
      setSelectedVersionId(created.id);
      setMessage("价格版本草稿已创建");
      await queryClient.invalidateQueries({
        queryKey: ["admin-price-versions"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["admin-price-modules", created.id],
      });
    },
  });

  const saveModules = useMutation({
    mutationFn: async () => {
      if (!selectedVersionId) throw new Error("请先创建或选择价格版本");
      for (const price of modulePrices) {
        await adminApi.upsertModulePrice(
          selectedVersionId,
          price.module,
          price,
        );
      }
    },
    onSuccess: async () => {
      setMessage("模块价格已保存");
      await queryClient.invalidateQueries({
        queryKey: ["admin-price-versions"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["admin-price-modules", selectedVersionId],
      });
    },
  });

  const publish = useMutation({
    mutationFn: (id: string) =>
      adminApi.publishPriceVersion(
        id,
        effectiveAt ? new Date(effectiveAt).toISOString() : undefined,
      ),
    onSuccess: async () => {
      setMessage("价格版本已发布");
      await queryClient.invalidateQueries({
        queryKey: ["admin-price-versions"],
      });
    },
  });

  function create(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    createVersion.mutate();
  }

  function updateModule(index: number, patch: Partial<ModulePrice>) {
    setModulePrices((items) =>
      items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  }

  return (
    <div className="space-y-5">
      <div className="glass p-5">
        <h1 className="text-xl font-semibold">积分价格版本</h1>
        <p className="mt-1 text-sm text-text-3">
          同一时刻只发布一个版本，新任务使用新价格，已创建任务保留价格快照。
        </p>
        <form className="mt-4 flex flex-wrap gap-3" onSubmit={create}>
          <input
            className="input max-w-xs"
            value={version}
            onChange={(event) => setVersion(event.target.value)}
          />
          <button
            className="btn-primary"
            disabled={createVersion.isPending || !version}
          >
            创建版本
          </button>
          <select
            className="input max-w-xs"
            value={selectedVersionId}
            onChange={(event) => setSelectedVersionId(event.target.value)}
          >
            <option value="">选择价格版本</option>
            {data.map((item) => (
              <option key={item.id} value={item.id}>
                {item.version} · {item.status}
              </option>
            ))}
          </select>
          <input
            className="input max-w-xs"
            type="datetime-local"
            aria-label="价格生效时间"
            value={effectiveAt}
            onChange={(event) => setEffectiveAt(event.target.value)}
          />
          <button
            type="button"
            className="btn-ghost"
            disabled={
              !selectedVersionId ||
              selected?.status !== "draft" ||
              publish.isPending
            }
            onClick={() => publish.mutate(selectedVersionId)}
          >
            {effectiveAt ? "定时发布" : "发布当前版本"}
          </button>
        </form>
        {isLoading && <p className="mt-3 text-sm text-text-3">加载中...</p>}
        {(message ||
          error ||
          createVersion.error ||
          saveModules.error ||
          publish.error) && (
          <p className="mt-3 text-sm text-text-2">
            {[
              error,
              createVersion.error,
              saveModules.error,
              publish.error,
            ].find((item) => item instanceof Error)?.message || message}
          </p>
        )}
      </div>

      <section className="glass p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-medium">模块积分配置</h2>
          <button
            className="btn-primary"
            disabled={
              !selectedVersionId ||
              selected?.status !== "draft" ||
              saveModules.isPending
            }
            onClick={() => saveModules.mutate()}
          >
            保存模块价格
          </button>
        </div>
        <div className="space-y-4">
          {modulePrices.map((price, index) => (
            <article
              key={price.module}
              className="grid gap-3 rounded-2xl border border-stroke bg-white/[0.03] p-4 lg:grid-cols-8"
            >
              <Field
                className="lg:col-span-1"
                label="模块"
                value={price.module}
                onChange={() => undefined}
                readOnly
              />
              <Field
                className="lg:col-span-2"
                label="名称"
                value={price.displayName}
                onChange={(displayName) => updateModule(index, { displayName })}
              />
              <Select
                className="lg:col-span-1"
                label="单位"
                value={price.billingUnit}
                units={moduleBillingUnits[price.module] ?? ["per_action"]}
                onChange={(billingUnit) => updateModule(index, { billingUnit })}
              />
              <NumberField
                label="单位大小"
                value={price.unitSize}
                onChange={(unitSize) => updateModule(index, { unitSize })}
              />
              <NumberField
                label="每单位积分"
                value={price.pointsPerUnit}
                onChange={(pointsPerUnit) =>
                  updateModule(index, { pointsPerUnit })
                }
              />
              <NumberField
                label="最低积分"
                value={price.minimumPoints}
                onChange={(minimumPoints) =>
                  updateModule(index, { minimumPoints })
                }
              />
              <label className="flex items-end gap-2 text-sm text-text-2">
                <input
                  type="checkbox"
                  checked={price.enabled}
                  onChange={(event) =>
                    updateModule(index, { enabled: event.target.checked })
                  }
                />
                启用
              </label>
              <Field
                className="lg:col-span-4"
                label="用户端说明"
                value={price.publicDescription}
                onChange={(publicDescription) =>
                  updateModule(index, { publicDescription })
                }
              />
              <NumberField
                label="内部成本（分）"
                value={price.internalCostCentsPerUnit || 0}
                onChange={(internalCostCentsPerUnit) =>
                  updateModule(index, { internalCostCentsPerUnit })
                }
              />
              <NumberField
                label="毛利 bps"
                value={price.targetMarginBps || 0}
                onChange={(targetMarginBps) =>
                  updateModule(index, { targetMarginBps })
                }
              />
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  className = "",
  readOnly = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
  readOnly?: boolean;
}) {
  return (
    <label className={className}>
      <span className="label">{label}</span>
      <input
        className="input"
        value={value}
        readOnly={readOnly}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      <span className="label">{label}</span>
      <input
        className="input"
        type="number"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function Select({
  label,
  value,
  units,
  onChange,
  className = "",
}: {
  label: string;
  value: string;
  units: string[];
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <label className={className}>
      <span className="label">{label}</span>
      <select
        className="input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {units.map((unit) => (
          <option key={unit} value={unit}>
            {unit}
          </option>
        ))}
      </select>
    </label>
  );
}
