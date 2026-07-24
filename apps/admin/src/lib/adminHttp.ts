export const ADMIN_TOKEN_KEY = "oral_admin_access_token";

const baseUrl = (
  import.meta.env.VITE_ADMIN_API_BASE || "/api/admin/v1"
).replace(/\/$/, "");

export interface TokensOut {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

export interface PlanSku {
  id: string;
  code: string;
  name: string;
  subtitle?: string;
  description?: string;
  badge?: string;
  sortOrder?: number;
  skuType: "trial" | "annual_bundle" | "internal_annual" | "points_pack";
  audience: "public" | "internal";
  status: "draft" | "scheduled" | "published" | "retired";
  version: number;
  durationDays: number;
  monthlyPoints: number;
  oneTimePoints: number;
  listPriceCents: number;
  displayPriceCents: number;
  entitlements: string[];
  maxConcurrency: number;
  maxResolution: string;
  purchaseInstructions?: string;
}

export interface ModulePrice {
  module: string;
  displayName: string;
  billingUnit: string;
  unitSize: number;
  pointsPerUnit: number;
  minimumPoints: number;
  enabled: boolean;
  publicDescription: string;
  internalCostCentsPerUnit?: number;
  targetMarginBps?: number;
}

export interface PriceVersion {
  id: string;
  version: string;
  status: "draft" | "scheduled" | "published" | "retired";
  items?: ModulePrice[];
  effectiveAt?: string | null;
  publishedAt?: string | null;
  retiredAt?: string | null;
}

export interface ActivationBatch {
  batchId: string;
  generated: number;
  codes: string[];
}

export interface ProviderConfig {
  provider: string;
  displayName: string;
  enabled: boolean;
  baseUrl: string;
  model?: string;
  priority?: number;
  apiKeyConfigured?: boolean;
  apiKey?: string;
}

export type AdminRole = "user" | "admin" | "ops" | "finance" | "auditor";

export interface AdminUser {
  id: string;
  phone: string;
  nickname: string;
  role: AdminRole;
  isActive: boolean;
  planType: string;
  planSkuCode: string;
  planExpiresAt?: string | null;
  balance: number;
  createdAt: string;
}

export interface CostAnalysisItem {
  module: string;
  displayName: string;
  pointsPerUnit: number;
  internalCostCentsPerUnit: number;
  targetMarginBps: number;
  enabled: boolean;
}

/** 运营总览聚合指标（GET /admin/overview） */
export interface AdminOverview {
  totalUsers: number;
  newUsersToday: number;
  totalTasks: number;
  doneTasksToday: number;
  totalCodes: number;
  usedCodes: number;
  totalGranted: number;
  totalConsumed: number;
  expiringSubscriptions: number;
}

export interface AuditItem {
  id: string;
  event: string;
  userId: string;
  traceId: string;
  taskId: string;
  detail: string;
  createdAt: string;
}

export interface ImKillSwitchStatus {
  stopped: boolean;
  canceledMessages: number;
}

export interface ImGrayAccount {
  accountId: string;
  userId: string;
  nickname: string;
  approvedBy: string;
  addedAt: string;
}

export interface ImMonitoringSummary {
  hours: number;
  windowStart: string;
  windowEnd: string;
  grayAccounts: number;
  listenerAccounts: number;
  listeningAccounts: number;
  connectionAttempts: number;
  connectionSuccessRate: number;
  dropoutRate: number;
  sendSuccessRate: number;
  sendSuccess: number;
  sendFailure: number;
  quotaRejected: number;
  moderationBlocked: number;
  credentialExpired: number;
  ownershipRejected: number;
  riskControlIncidents: number;
}

interface ProviderSettingsResponse {
  settings: Record<string, string>;
}

const providerDefinitions = [
  {
    provider: "deepseek",
    displayName: "DeepSeek / LLM",
    key: "deepseek_api_key",
    baseUrl: "deepseek_base_url",
    model: "deepseek_model",
    enabled: "deepseek_enabled",
    priority: "deepseek_priority",
  },
  {
    provider: "dashscope_asr",
    displayName: "DashScope ASR",
    key: "dashscope_api_key",
    model: "asr_model",
    enabled: "dashscope_enabled",
    priority: "dashscope_priority",
    defaultBaseUrl: "https://dashscope.aliyuncs.com",
  },
  {
    provider: "hifly",
    displayName: "HiFly 数字人/声音",
    key: "feiying_api_key",
    baseUrl: "feiying_base_url",
    enabled: "feiying_enabled",
    priority: "feiying_priority",
  },
  {
    provider: "douyidou",
    displayName: "Douyidou 视频解析",
    key: "douyidou_app_secret",
    baseUrl: "douyidou_base_url",
    enabled: "douyidou_enabled",
    priority: "douyidou_priority",
  },
] as const;

function providerFromSettings(
  definition: (typeof providerDefinitions)[number],
  settings: Record<string, string>,
): ProviderConfig {
  const baseUrlKey = "baseUrl" in definition ? definition.baseUrl : undefined;
  const modelKey = "model" in definition ? definition.model : undefined;
  return {
    provider: definition.provider,
    displayName: definition.displayName,
    enabled: settings[definition.enabled] === "true",
    baseUrl:
      (baseUrlKey && settings[baseUrlKey]) ||
      ("defaultBaseUrl" in definition ? definition.defaultBaseUrl : ""),
    model: (modelKey && settings[modelKey]) || "",
    priority: Number(settings[definition.priority] || 0),
    apiKeyConfigured: settings[definition.key] === "configured",
  };
}

export class AdminApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export function getAdminToken(): string | null {
  return localStorage.getItem(ADMIN_TOKEN_KEY);
}

export function setAdminToken(token: string): void {
  localStorage.setItem(ADMIN_TOKEN_KEY, token);
}

export function clearAdminToken(): void {
  localStorage.removeItem(ADMIN_TOKEN_KEY);
}

async function adminFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getAdminToken();
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body)
    headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${baseUrl}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = response.statusText || "请求失败";
    try {
      const body = await response.json();
      message = body?.detail?.message || body?.message || message;
    } catch {
      // 非 JSON 错误体保持 HTTP 状态文本。
    }
    throw new AdminApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const adminApi = {
  async login(phone: string, password: string): Promise<TokensOut> {
    const tokens = await adminFetch<TokensOut>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ phone, password }),
    });
    setAdminToken(tokens.accessToken);
    return tokens;
  },

  listPlans: () => adminFetch<PlanSku[]>("/plans"),
  createPlan: (body: Partial<PlanSku>) =>
    adminFetch<PlanSku>("/plans", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  publishPlan: (id: string, effectiveAt?: string) =>
    adminFetch<PlanSku>(`/plans/${id}/publish`, {
      method: "POST",
      body: effectiveAt ? JSON.stringify({ effectiveAt }) : undefined,
    }),
  clonePlan: (id: string) =>
    adminFetch<PlanSku>(`/plans/${id}/clone`, { method: "POST" }),
  retirePlan: (id: string) =>
    adminFetch<PlanSku>(`/plans/${id}/retire`, { method: "POST" }),

  listPriceVersions: () => adminFetch<PriceVersion[]>("/price-versions"),
  listModulePrices: (versionId: string) =>
    adminFetch<ModulePrice[]>(`/price-versions/${versionId}/modules`),
  createPriceVersion: (version: string) =>
    adminFetch<PriceVersion>("/price-versions", {
      method: "POST",
      body: JSON.stringify({ version }),
    }),
  upsertModulePrice: (versionId: string, module: string, body: ModulePrice) =>
    adminFetch<ModulePrice>(`/price-versions/${versionId}/modules/${module}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  publishPriceVersion: (id: string, effectiveAt?: string) =>
    adminFetch<PriceVersion>(`/price-versions/${id}/publish`, {
      method: "POST",
      body: effectiveAt ? JSON.stringify({ effectiveAt }) : undefined,
    }),

  generateActivationBatch: (body: {
    name: string;
    skuVersionId: string;
    count: number;
    channel: string;
  }) =>
    adminFetch<ActivationBatch>("/activation/batches", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listUsers: () => adminFetch<{ items: AdminUser[]; total: number }>("/users"),
  updateUser: (id: string, body: { role?: AdminRole; isActive?: boolean }) =>
    adminFetch<{ id: string; role: AdminRole; isActive: boolean }>(
      `/users/${id}`,
      {
        method: "PATCH",
        body: JSON.stringify(body),
      },
    ),
  // 扣减或大额（|points|>=10000）调整必须 confirm=true（服务端二次确认）
  adjustUserCredits: (
    id: string,
    body: { points: number; reason: string; confirm?: boolean },
  ) =>
    adminFetch<{ balance: number }>(`/users/${id}/credits/adjust`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  costAnalysis: () =>
    adminFetch<{ priceVersion: string | null; items: CostAnalysisItem[] }>(
      "/cost-analysis",
    ),
  overview: () => adminFetch<AdminOverview>("/overview"),
  audit: () => adminFetch<{ items: AuditItem[]; total: number }>("/audit"),
  imKillSwitch: () => adminFetch<ImKillSwitchStatus>("/im/kill-switch"),
  setImKillSwitch: (stopped: boolean) =>
    adminFetch<ImKillSwitchStatus>("/im/kill-switch", {
      method: "PUT",
      body: JSON.stringify({ stopped }),
    }),
  listImGrayAccounts: () => adminFetch<ImGrayAccount[]>("/im/gray/accounts"),
  approveImGrayAccount: (accountId: string) =>
    adminFetch<ImGrayAccount>(`/im/gray/accounts/${accountId}`, {
      method: "PUT",
    }),
  removeImGrayAccount: (accountId: string) =>
    adminFetch<{ ok: boolean }>(`/im/gray/accounts/${accountId}`, {
      method: "DELETE",
    }),
  imMonitoring: (hours = 24) =>
    adminFetch<ImMonitoringSummary>(`/im/monitoring?hours=${hours}`),
  recordImRiskIncident: (accountId: string, detail: string) =>
    adminFetch<{ ok: boolean }>("/im/monitoring/incidents", {
      method: "POST",
      body: JSON.stringify({ accountId, detail }),
    }),

  async listProviders(): Promise<ProviderConfig[]> {
    const response = await adminFetch<ProviderSettingsResponse>("/providers");
    return providerDefinitions.map((definition) =>
      providerFromSettings(definition, response.settings),
    );
  },
  async saveProvider(
    provider: string,
    body: ProviderConfig,
  ): Promise<ProviderConfig> {
    const definition = providerDefinitions.find(
      (item) => item.provider === provider,
    );
    if (!definition) throw new AdminApiError("未知 Provider", 400);
    const settings: Record<string, string> = {
      [definition.enabled]: String(body.enabled),
      [definition.priority]: String(body.priority || 0),
    };
    if (body.apiKey) settings[definition.key] = body.apiKey;
    if ("baseUrl" in definition && body.baseUrl)
      settings[definition.baseUrl] = body.baseUrl;
    if ("model" in definition && body.model)
      settings[definition.model] = body.model;
    await adminFetch<ProviderSettingsResponse>("/providers", {
      method: "PUT",
      body: JSON.stringify({ settings }),
    });
    return {
      ...body,
      apiKey: "",
      apiKeyConfigured: body.apiKeyConfigured || Boolean(body.apiKey),
    };
  },
};
