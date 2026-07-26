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
  appId?: string;
  model?: string;
  workspaceId?: string;
  region?: string;
  flashModel?: string;
  flashThresholdSec?: number;
  apiKeyConfigured?: boolean;
  apiKey?: string;
  configured?: boolean;
  missingFields?: string[];
  probeMode?: "credential" | "sample";
}

export interface ProviderProbeResult {
  provider: string;
  status: "verified" | "failed" | "incomplete" | "needs_sample";
  message: string;
  details: Record<string, unknown>;
}

export interface AdminUser {
  id: string;
  phone: string | null;
  nickname: string;
  role: "user" | "admin";
  isActive: boolean;
  planType: string;
  planSkuCode: string;
  planExpiresAt?: string | null;
  deviceBound: boolean;
  activationCodeMasked?: string | null;
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

export interface DashboardKpis {
  totalUsers: number;
  newUsersToday: number;
  newUsersYesterday: number;
  pointsConsumedToday: number;
  pointsConsumedYesterday: number;
  tasksCreatedToday: number;
  tasksCreatedYesterday: number;
  publishSuccessRate: number | null;
  codesUnused: number;
  codesActivatedTotal: number;
  revenueCentsWindow: number;
  costCentsWindow: number;
}

export interface DashboardOut {
  rangeDays: number;
  generatedAt: string;
  dates: string[];
  kpis: DashboardKpis;
  users: { newUsers: number[]; cumulativeUsers: number[] };
  activation: { created: number[]; activated: number[] };
  credits: { granted: number[]; consumed: number[] };
  production: {
    tasksCreated: number[];
    tasksSucceeded: number[];
    tasksFailed: number[];
    voiceClones: number[];
    avatarTrainings: number[];
  };
  publishing: { created: number[]; succeeded: number[]; failed: number[] };
  economics: { revenueCents: number[]; costCents: number[] };
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

interface ProviderStatusResponse {
  items: Array<{
    provider: string;
    enabled: boolean;
    configured: boolean;
    missingFields: string[];
    probeMode: "credential" | "sample";
  }>;
}

const providerDefinitions = [
  {
    provider: "deepseek",
    displayName: "DeepSeek / LLM",
    key: "deepseek_api_key",
    baseUrl: "deepseek_base_url",
    model: "deepseek_model",
    enabled: "deepseek_enabled",
  },
  {
    provider: "dashscope_asr",
    displayName: "DashScope ASR",
    key: "dashscope_api_key",
    workspaceId: "dashscope_workspace_id",
    region: "dashscope_region",
    model: "asr_model",
    flashModel: "asr_flash_model",
    flashThresholdSec: "asr_flash_threshold_sec",
    enabled: "dashscope_enabled",
    defaultBaseUrl: "https://dashscope.aliyuncs.com",
  },
  {
    provider: "hifly",
    displayName: "HiFly 数字人/声音",
    key: "feiying_api_key",
    baseUrl: "feiying_base_url",
    enabled: "feiying_enabled",
  },
  {
    provider: "douyidou",
    displayName: "Douyidou 视频解析",
    appId: "douyidou_app_id",
    key: "douyidou_app_secret",
    baseUrl: "douyidou_base_url",
    enabled: "douyidou_enabled",
  },
] as const;

function providerFromSettings(
  definition: (typeof providerDefinitions)[number],
  settings: Record<string, string>,
): ProviderConfig {
  const baseUrlKey = "baseUrl" in definition ? definition.baseUrl : undefined;
  const appIdKey = "appId" in definition ? definition.appId : undefined;
  const modelKey = "model" in definition ? definition.model : undefined;
  const workspaceIdKey =
    "workspaceId" in definition ? definition.workspaceId : undefined;
  const regionKey = "region" in definition ? definition.region : undefined;
  const flashModelKey =
    "flashModel" in definition ? definition.flashModel : undefined;
  const flashThresholdSecKey =
    "flashThresholdSec" in definition
      ? definition.flashThresholdSec
      : undefined;
  const appId = (appIdKey && settings[appIdKey]) || "";
  return {
    provider: definition.provider,
    displayName: definition.displayName,
    enabled: settings[definition.enabled] === "true",
    baseUrl:
      (baseUrlKey && settings[baseUrlKey]) ||
      ("defaultBaseUrl" in definition ? definition.defaultBaseUrl : ""),
    appId,
    model: (modelKey && settings[modelKey]) || "",
    workspaceId: (workspaceIdKey && settings[workspaceIdKey]) || "",
    region: (regionKey && settings[regionKey]) || "",
    flashModel: (flashModelKey && settings[flashModelKey]) || "",
    flashThresholdSec: Number(
      (flashThresholdSecKey && settings[flashThresholdSecKey]) || 0,
    ),
    apiKeyConfigured:
      settings[definition.key] === "configured" &&
      (!appIdKey || Boolean(appId)),
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
  dashboard: (days = 30) => adminFetch<DashboardOut>(`/dashboard?days=${days}`),
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
  updateUser: (
    id: string,
    body: { role?: "user" | "admin"; isActive?: boolean },
  ) =>
    adminFetch<{ id: string; role: "user" | "admin"; isActive: boolean }>(
      `/users/${id}`,
      {
        method: "PATCH",
        body: JSON.stringify(body),
      },
    ),
  adjustUserCredits: (id: string, body: { points: number; reason: string }) =>
    adminFetch<{ balance: number }>(`/users/${id}/credits/adjust`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  unbindDevice: (id: string) =>
    adminFetch<{ ok: boolean }>(`/users/${id}/unbind-device`, {
      method: "POST",
    }),
  costAnalysis: () =>
    adminFetch<{ priceVersion: string | null; items: CostAnalysisItem[] }>(
      "/cost-analysis",
    ),
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
    const [response, statusResponse] = await Promise.all([
      adminFetch<ProviderSettingsResponse>("/providers"),
      adminFetch<ProviderStatusResponse>("/providers/status"),
    ]);
    return providerDefinitions.map((definition) => {
      const provider = providerFromSettings(definition, response.settings);
      const status = statusResponse.items.find(
        (item) => item.provider === definition.provider,
      );
      return {
        ...provider,
        configured: status?.configured ?? provider.apiKeyConfigured,
        missingFields: status?.missingFields ?? [],
        probeMode: status?.probeMode ?? "credential",
      };
    });
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
    };
    if ("appId" in definition && body.appId)
      settings[definition.appId] = body.appId;
    if (body.apiKey) settings[definition.key] = body.apiKey;
    if ("baseUrl" in definition && body.baseUrl)
      settings[definition.baseUrl] = body.baseUrl;
    if ("model" in definition && body.model)
      settings[definition.model] = body.model;
    if ("workspaceId" in definition)
      settings[definition.workspaceId] = body.workspaceId || "";
    if ("region" in definition && body.region)
      settings[definition.region] = body.region;
    if ("flashModel" in definition && body.flashModel)
      settings[definition.flashModel] = body.flashModel;
    if ("flashThresholdSec" in definition && body.flashThresholdSec)
      settings[definition.flashThresholdSec] = String(body.flashThresholdSec);
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
  probeProvider: (provider: string) =>
    adminFetch<ProviderProbeResult>(`/providers/${provider}/probe`, {
      method: "POST",
    }),
};
