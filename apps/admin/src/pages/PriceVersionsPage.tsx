import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { adminApi, type ModulePrice } from "../lib/adminHttp";

/** 计费单位：编码 → 运营可读文案 */
const BILLING_UNIT_LABELS: Record<string, string> = {
  per_action: "按次",
  per_1k_chars: "每 1000 字",
  per_1k_tokens: "每 1000 Token",
  per_minute: "每分钟",
  per_second: "每秒",
  per_asset: "每个资产",
  per_image: "每张图片",
};

/** 计费单位对应的默认单位大小 */
const UNIT_SIZE_BY_BILLING: Record<string, number> = {
  per_action: 1,
  per_1k_chars: 1000,
  per_1k_tokens: 1000,
  per_minute: 60,
  per_second: 1,
  per_asset: 1,
  per_image: 1,
};

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  scheduled: "待生效",
  published: "已发布",
  retired: "已下架",
};

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

/** 根据计费单位和积分自动生成用户端说明 */
function buildPublicDescription(price: ModulePrice): string {
  const unitLabel = BILLING_UNIT_LABELS[price.billingUnit] ?? price.billingUnit;
  if (price.pointsPerUnit <= 0) return `${unitLabel}计费`;
  return `${unitLabel} ${price.pointsPerUnit} 积分`;
}

export default function PriceVersionsPage() {
  const queryClient = useQueryClient();
  const [version, setVersion] = useState(
    `price-${new Date().toISOString().slice(0, 10)}`,
  );
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [modulePrices, setModulePrices] = useState(defaultModules);
  const [message, setMessage] = useState("");
  const [effectiveAt, setEffectiveAt] = useState("");
  const [expandedCost, setExpandedCost] = useState<Record<string, boolean>>({});
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
      items.map((item, i) => {
        if (i !== index) return item;
        const next = { ...item, ...patch };
        // 切换计费单位时同步单位大小，并自动更新用户端说明
        if (patch.billingUnit) {
          next.unitSize = UNIT_SIZE_BY_BILLING[patch.billingUnit] ?? 1;
        }
        if (
          patch.billingUnit !== undefined ||
          patch.pointsPerUnit !== undefined
        ) {
          next.publicDescription = buildPublicDescription(next);
        }
        return next;
      }),
    );
  }

  const editable = Boolean(selectedVersionId) && selected?.status === "draft";

  return (
    <div className="space-y-5">
      <div className="glass p-6">
        <h1 className="font-serif text-2xl font-semibold tracking-wide">
          积分价格
        </h1>
        <p className="mt-1 text-sm text-text-3">
          同一时刻只有一个生效版本；发布新版本后，新任务用新价格，进行中的任务保留下单时的价格。
        </p>

        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <form className="space-y-3" onSubmit={create}>
            <p className="border-b border-stroke pb-2 text-sm font-medium tracking-widest">
              第一步 · 创建或选择版本
            </p>
            <div className="flex flex-wrap gap-3">
              <label className="min-w-52 flex-1">
                <span className="label">新版本名称</span>
                <input
                  className="input"
                  value={version}
                  onChange={(event) => setVersion(event.target.value)}
                />
              </label>
              <button
                className="btn-primary self-end"
                disabled={createVersion.isPending || !version}
              >
                创建草稿版本
              </button>
            </div>
            <label className="block">
              <span className="label">或选择已有版本继续编辑</span>
              <select
                className="input"
                value={selectedVersionId}
                onChange={(event) => setSelectedVersionId(event.target.value)}
              >
                <option value="">选择价格版本</option>
                {data.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.version} · {STATUS_LABELS[item.status] ?? item.status}
                  </option>
                ))}
              </select>
            </label>
          </form>

          <div className="space-y-3">
            <p className="border-b border-stroke pb-2 text-sm font-medium tracking-widest">
              第二步 · 发布生效
            </p>
            <label className="block">
              <span className="label">定时生效时间（留空则立即生效）</span>
              <input
                className="input"
                type="datetime-local"
                aria-label="价格生效时间"
                value={effectiveAt}
                onChange={(event) => setEffectiveAt(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn-ghost w-full"
              disabled={!editable || publish.isPending}
              onClick={() => publish.mutate(selectedVersionId)}
            >
              {effectiveAt ? "定时发布当前版本" : "立即发布当前版本"}
            </button>
            {selected && (
              <p className="text-sm text-text-3">
                当前编辑：{selected.version} ·{" "}
                {STATUS_LABELS[selected.status] ?? selected.status}
                {selected.status !== "draft" && "（非草稿版本不可修改）"}
              </p>
            )}
          </div>
        </div>

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

      <section className="glass p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="font-serif text-xl font-semibold tracking-wide">
              各功能计费规则
            </h2>
            <p className="mt-1 text-sm text-text-3">
              这里配置的是用户消耗积分的规则；内部成本仅用于毛利测算，用户不可见。
            </p>
          </div>
          <button
            className="btn-primary"
            disabled={!editable || saveModules.isPending}
            onClick={() => saveModules.mutate()}
          >
            保存计费规则
          </button>
        </div>
        <div className="space-y-3">
          {modulePrices.map((price, index) => (
            <article
              key={price.module}
              className={`rounded-2xl border border-stroke bg-white/[0.03] p-4 ${
                price.enabled ? "" : "opacity-60"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium">{price.displayName}</h3>
                    <span className="chip">{price.module}</span>
                  </div>
                  <p className="mt-1 text-sm text-text-3">
                    用户端展示：{price.publicDescription || "（自动生成）"}
                  </p>
                </div>
                <label className="flex items-center gap-2 text-sm text-text-2">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-accent"
                    checked={price.enabled}
                    onChange={(event) =>
                      updateModule(index, { enabled: event.target.checked })
                    }
                  />
                  {price.enabled ? "已启用" : "已停用"}
                </label>
              </div>

              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <label>
                  <span className="label">计费方式</span>
                  <select
                    className="input"
                    value={price.billingUnit}
                    onChange={(event) =>
                      updateModule(index, { billingUnit: event.target.value })
                    }
                  >
                    {(moduleBillingUnits[price.module] ?? ["per_action"]).map(
                      (unit) => (
                        <option key={unit} value={unit}>
                          {BILLING_UNIT_LABELS[unit] ?? unit}
                        </option>
                      ),
                    )}
                  </select>
                </label>
                <NumberField
                  label={`积分单价（${BILLING_UNIT_LABELS[price.billingUnit] ?? price.billingUnit}）`}
                  value={price.pointsPerUnit}
                  onChange={(pointsPerUnit) =>
                    updateModule(index, { pointsPerUnit })
                  }
                />
                <NumberField
                  label="单次最低扣除积分"
                  value={price.minimumPoints}
                  onChange={(minimumPoints) =>
                    updateModule(index, { minimumPoints })
                  }
                />
                <label>
                  <span className="label">用户端说明（可改）</span>
                  <input
                    className="input"
                    value={price.publicDescription}
                    onChange={(event) =>
                      updateModule(index, {
                        publicDescription: event.target.value,
                      })
                    }
                  />
                </label>
              </div>

              <button
                type="button"
                className="mt-3 text-sm text-text-3 underline-offset-4 hover:text-text-2 hover:underline"
                onClick={() =>
                  setExpandedCost((prev) => ({
                    ...prev,
                    [price.module]: !prev[price.module],
                  }))
                }
              >
                {expandedCost[price.module]
                  ? "收起内部成本设置"
                  : "高级选项：内部成本与毛利（用户不可见）"}
              </button>
              {expandedCost[price.module] && (
                <div className="mt-3 grid gap-3 border-t border-stroke pt-3 sm:grid-cols-2 lg:grid-cols-4">
                  <NumberField
                    label="内部成本（分/单位）"
                    value={price.internalCostCentsPerUnit || 0}
                    onChange={(internalCostCentsPerUnit) =>
                      updateModule(index, { internalCostCentsPerUnit })
                    }
                  />
                  <NumberField
                    label="目标毛利（bps，6000 = 60%）"
                    value={price.targetMarginBps || 0}
                    onChange={(targetMarginBps) =>
                      updateModule(index, { targetMarginBps })
                    }
                  />
                  <label>
                    <span className="label">内部备注名称</span>
                    <input
                      className="input"
                      value={price.displayName}
                      onChange={(event) =>
                        updateModule(index, {
                          displayName: event.target.value,
                        })
                      }
                    />
                  </label>
                  <NumberField
                    label="单位大小（自动带出）"
                    value={price.unitSize}
                    onChange={(unitSize) => updateModule(index, { unitSize })}
                  />
                </div>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
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
