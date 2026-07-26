/**
 * API 端点封装（对齐后端 FastAPI 路由，契约同源）
 */
import type {
  AuthTokens,
  Avatar,
  BatchRewriteResult,
  ContentJob,
  DashboardOverview,
  FeedEvent,
  ModulePriceCatalog,
  Notification,
  Page,
  ParseResult,
  Persona,
  PlanSku,
  PipelineMode,
  PipelineTask,
  Platform,
  PricePreview,
  PricePreviewRequest,
  PublishAccount,
  PublishCapability,
  PublishJob,
  Quota,
  QuotaUsageItem,
  RewriteIntensity,
  RewriteResult,
  Script,
  SimilarityResult,
  Subscription,
  TaskStats,
  User,
  Voice,
  WordTimestamp,
} from "@oral/types";
import { HttpError, http } from "./http";
import { deviceFingerprint } from "./fingerprint";

// ---------- auth（激活码即账号） ----------
export const authApi = {
  login: async (code: string) =>
    http.post<AuthTokens>("/auth/login", {
      code,
      deviceFingerprint: await deviceFingerprint(),
    }),
  me: () => http.get<User>("/auth/me"),
};

// ---------- activation（激活码） ----------
export interface CodeInfo {
  valid: boolean;
  planType: string;
  quotaAmount: number;
  durationDays: number;
  message: string;
}

export interface RedeemResult {
  planType: string;
  planExpiresAt: string | null;
  quotaGranted: number;
  newBalance: number;
}

export const activationApi = {
  validateCode: async (code: string) =>
    http.post<CodeInfo>("/activation/validate-code", {
      code,
      deviceFingerprint: await deviceFingerprint(),
    }),
  redeem: (code: string) =>
    http.post<RedeemResult>("/activation/redeem", { code }),
  subscription: () => http.get<Subscription>("/subscription"),
};

// ---------- catalog（用户端套餐与积分价格） ----------
export const catalogApi = {
  plans: () => http.get<PlanSku[]>("/catalog/plans"),
  modulePrices: () => http.get<ModulePriceCatalog>("/catalog/module-prices"),
};

// ---------- billing ----------
export const billingApi = {
  quota: () => http.get<Quota>("/billing/quota"),
  usage: (page = 1, pageSize = 20) =>
    http.get<Page<QuotaUsageItem>>(
      `/billing/usage?page=${page}&pageSize=${pageSize}`,
    ),
  pricePreview: (input: PricePreviewRequest) =>
    http.post<PricePreview>("/billing/price-preview", input),
  exportCsvUrl: () => `/api/v1/billing/usage?export=csv`,
};

// ---------- personas / ipasset ----------
export const personaApi = {
  list: () => http.get<Persona[]>("/personas"),
  get: (id: string) => http.get<Persona>(`/personas/${id}`),
  create: (data: Partial<Persona>) => http.post<Persona>("/personas", data),
  update: (id: string, data: Partial<Persona>) =>
    http.put<Persona>(`/personas/${id}`, data),
  activate: (id: string) => http.post<Persona>(`/personas/${id}/activate`),
};

// ---------- content（文案模块 F-101~F-106） ----------
export type ContentJobProgress = Pick<
  ContentJob,
  "id" | "status" | "progress" | "stage"
>;

const CONTENT_JOB_POLL_MS = 800;
const CONTENT_JOB_TIMEOUT_MS = 30 * 60 * 1000;

async function waitForContentJob<TResult>(
  submitted: ContentJob<TResult>,
  onProgress?: (progress: ContentJobProgress) => void,
): Promise<TResult> {
  const deadline = Date.now() + CONTENT_JOB_TIMEOUT_MS;
  let job = submitted;
  while (true) {
    onProgress?.(job);
    if (job.status === "done" && job.result) return job.result;
    if (job.status === "failed") {
      throw new HttpError(502, {
        code: "CONTENT_JOB_FAILED",
        message: job.error || "后台文案任务执行失败",
      });
    }
    if (Date.now() >= deadline) {
      throw new HttpError(504, {
        code: "CONTENT_JOB_TIMEOUT",
        message: "后台任务仍在执行，请稍后重试",
      });
    }
    await new Promise((resolve) =>
      window.setTimeout(resolve, CONTENT_JOB_POLL_MS),
    );
    job = await http.get<ContentJob<TResult>>(`/content/jobs/${job.id}`);
  }
}

export const contentApi = {
  probe: (url: string) =>
    http.post<{ durationSeconds: number }>("/content/probe", { url }),
  parse: (
    url?: string,
    file?: File,
    quoteId?: string,
    onProgress?: (progress: ContentJobProgress) => void,
  ): Promise<ParseResult> => {
    let request: Promise<ContentJob<ParseResult>>;
    if (file) {
      const fd = new FormData();
      fd.append("file", file);
      if (quoteId) fd.append("quoteId", quoteId);
      request = http.post<ContentJob<ParseResult>>("/content/jobs/parse", fd);
    } else {
      const fd = new FormData();
      if (url) fd.append("url", url);
      if (quoteId) fd.append("quoteId", quoteId);
      request = http.post<ContentJob<ParseResult>>("/content/jobs/parse", fd);
    }
    return request.then((job) => waitForContentJob(job, onProgress));
  },
  rewrite: (
    text: string,
    intensity: RewriteIntensity,
    prompt?: string,
    scriptId?: string,
    quoteId?: string,
    onProgress?: (progress: ContentJobProgress) => void,
  ) =>
    http
      .post<ContentJob<RewriteResult>>("/content/jobs/rewrite", {
        text,
        intensity,
        prompt,
        scriptId,
        quoteId,
      })
      .then((job) => waitForContentJob(job, onProgress)),
  batchRewrite: (
    text: string,
    intensity: RewriteIntensity,
    count = 3,
    prompt?: string,
    scriptId?: string,
    quoteId?: string,
  ) =>
    http.post<BatchRewriteResult>("/content/rewrite/batch", {
      text,
      intensity,
      count,
      prompt,
      scriptId,
      quoteId,
    }),
  similarity: (
    text: string,
    quoteId?: string,
    onProgress?: (progress: ContentJobProgress) => void,
  ) =>
    http
      .post<ContentJob<SimilarityResult>>("/content/jobs/similarity", {
        text,
        quoteId,
      })
      .then((job) => waitForContentJob(job, onProgress)),
  topics: (keyword: string, quoteId?: string) =>
    http.post<{ topics: string[] }>("/content/topics", { keyword, quoteId }),
  scripts: () => http.get<Script[]>("/content/scripts"),
  script: (id: string) => http.get<Script>(`/content/scripts/${id}`),
  createScript: (input: {
    title?: string;
    text: string;
    platform?: string;
    topic?: string;
  }) => http.post<Script>("/content/scripts", input),
};

// ---------- voices / avatars（克隆强制 consent_token；绑定 IP 走 personaApi.update） ----------
export const voiceApi = {
  list: () => http.get<Voice[]>("/voices"),
  clone: (name: string, consentToken: string, file: File, quoteId?: string) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("consentToken", consentToken);
    fd.append("file", file);
    if (quoteId) fd.append("quoteId", quoteId);
    return http.post<Voice>("/voices/clone", fd);
  },
  status: (voiceId: string) =>
    http.get<Pick<Voice, "id" | "status" | "demoUrl">>(
      `/voices/${voiceId}/status`,
    ),
  confirm: (voiceId: string) => http.post<Voice>(`/voices/${voiceId}/confirm`),
  reject: (voiceId: string) => http.post<Voice>(`/voices/${voiceId}/reject`),
  synthesize: (voiceId: string, text: string, speed = 1.0, quoteId?: string) =>
    http.post<{ audioUrl: string; words: WordTimestamp[] }>(
      "/voices/synthesize",
      { voiceId, text, speed, quoteId },
    ),
};

export const avatarApi = {
  list: () => http.get<Avatar[]>("/avatars"),
  clone: (name: string, consentToken: string, file: File, quoteId?: string) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("consentToken", consentToken);
    fd.append("file", file);
    if (quoteId) fd.append("quoteId", quoteId);
    return http.post<Avatar>("/avatars/clone", fd);
  },
};

// ---------- pipeline（F-405/406） ----------
export interface CreatePipelineInput {
  ipId: string;
  sourceUrl?: string;
  topic?: string;
  scriptText?: string;
  voiceId?: string;
  avatarId?: string;
  mode: PipelineMode;
  platforms?: Platform[];
  publishAt?: string;
  randomize?: boolean;
  count?: number;
  quoteId?: string;
}

export const pipelineApi = {
  create: (input: CreatePipelineInput) =>
    http.post<PipelineTask[]>("/pipelines", input),
  list: (status?: string, page = 1, pageSize = 20) =>
    http.get<Page<PipelineTask>>(
      `/pipelines?page=${page}&pageSize=${pageSize}${status ? `&status=${status}` : ""}`,
    ),
  get: (id: string) => http.get<PipelineTask>(`/pipelines/${id}`),
  retryQuote: (id: string) =>
    http.post<PricePreview>(`/pipelines/${id}/retry-quote`),
  retryStep: (id: string, step: string, quoteId?: string) =>
    http.post<PipelineTask>(`/pipelines/${id}/steps/${step}/retry`, {
      quoteId,
    }),
  overrideStep: (id: string, step: string, artifacts: Record<string, string>) =>
    http.post<PipelineTask>(`/pipelines/${id}/steps/${step}/override`, {
      artifacts,
    }),
  confirm: (id: string) => http.post<PipelineTask>(`/pipelines/${id}/confirm`),
  cancel: (id: string) => http.post<PipelineTask>(`/pipelines/${id}/cancel`),
  stats: () => http.get<TaskStats>("/pipelines/stats"),
};

// ---------- publish（F-501~F-504） ----------
export interface CreatePublishInput {
  taskId?: string;
  platforms: Platform[];
  title: string;
  topics?: string[];
  videoKey: string;
  coverKey?: string;
  publishAt?: string;
}

export const publishApi = {
  capabilities: () => http.get<PublishCapability[]>("/publish/capabilities"),
  accounts: () => http.get<PublishAccount[]>("/publish/accounts"),
  qrcodeStart: (platform: Platform) =>
    http.post<{ ticket: string; qrcodeUrl: string }>(
      `/publish/accounts/qrcode?platform=${platform}`,
    ),
  qrcodePoll: (ticket: string, platform: Platform) =>
    http.get<{
      status: "waiting" | "success" | "expired";
      account?: PublishAccount | null;
      qrcodeUrl?: string | null;
      message?: string | null;
    }>(`/publish/accounts/qrcode/${ticket}?platform=${platform}`),
  reauth: (accountId: string) =>
    http.post<{ ticket: string; qrcodeUrl: string }>(
      `/publish/accounts/${accountId}/reauth`,
    ),
  deleteAccount: (accountId: string) =>
    http.delete<void>(`/publish/accounts/${accountId}`),
  renameAccount: (accountId: string, nickname: string) =>
    http.patch<PublishAccount>(`/publish/accounts/${accountId}`, { nickname }),
  jobs: (status?: string, page = 1, pageSize = 20) =>
    http.get<Page<PublishJob>>(
      `/publish/jobs?page=${page}&pageSize=${pageSize}${status ? `&status=${status}` : ""}`,
    ),
  logs: (page = 1, pageSize = 50) =>
    http.get<Page<PublishJob>>(
      `/publish/logs?page=${page}&pageSize=${pageSize}`,
    ),
  createJobs: (input: CreatePublishInput) =>
    http.post<PublishJob[]>("/publish/jobs", input),
  retryJob: (jobId: string) =>
    http.post<PublishJob>(`/publish/jobs/${jobId}/retry`),
  exportJob: (jobId: string) =>
    http.post<{
      jobId: string;
      videoUrl: string;
      packageKey: string;
      packageUrl: string;
      metadata: Record<string, unknown>;
    }>(`/publish/jobs/${jobId}/export`),
};

// ---------- notify（站内信） ----------
export const notifyApi = {
  list: () => http.get<Notification[]>("/notifications"),
  unreadCount: () => http.get<{ count: number }>("/notifications/unread-count"),
  markRead: (id: string) => http.post<void>(`/notifications/${id}/read`),
  markAllRead: () => http.post<void>("/notifications/read-all"),
};

// ---------- im（私信自动回复） ----------
export interface IMConversation {
  id: string;
  accountId: string;
  platform: string;
  remoteUid: string;
  remoteNickname: string;
  remoteAvatar: string;
  lastMessageAt: string;
  unreadCount: number;
  status: string;
  createdAt: string;
}

export interface IMMessage {
  id: string;
  conversationId: string;
  direction: "in" | "out";
  msgType: number;
  content: string;
  autoReplied: boolean;
  replyContent: string;
  sendStatus:
    | "received"
    | "suggested"
    | "blocked"
    | "scheduled"
    | "canceled"
    | "pending"
    | "sent"
    | "failed"
    | "manual";
  sendError: string;
  retryCount: number;
  manualTakeover: boolean;
  moderationStatus: "approved" | "blocked";
  moderationReason: string;
  createdAt: string;
}

export interface IMAutoReplyRule {
  id: string;
  accountId: string;
  name: string;
  triggerType: string;
  triggerPattern: string;
  replyMode: string;
  replyTemplate: string;
  llmPrompt: string;
  priority: number;
  dailyLimit: number;
  delayMin: number;
  delayMax: number;
  deliveryMode: "suggestion" | "auto";
  enabled: boolean;
  createdAt: string;
}

export interface IMListenerStatus {
  accountId: string;
  accountNickname?: string;
  platform: string;
  status: string;
  lastHeartbeat?: string | null;
  errorMsg: string;
  startedAt?: string | null;
}

export interface IMAutomationStatus {
  accountId: string;
  authorized: boolean;
  riskVersion: string;
  acceptedAt?: string | null;
}

export const imApi = {
  conversations: (page = 1, pageSize = 20, search = "", accountId = "") => {
    const params = new URLSearchParams({
      page: String(page),
      pageSize: String(pageSize),
    });
    if (search) params.set("search", search);
    if (accountId) params.set("accountId", accountId);
    return http.get<{
      items: IMConversation[];
      total: number;
      page: number;
      pageSize: number;
    }>(`/im/conversations?${params}`);
  },
  messages: (conversationId: string, page = 1, pageSize = 50, search = "") => {
    const params = new URLSearchParams({
      page: String(page),
      pageSize: String(pageSize),
    });
    if (search) params.set("search", search);
    return http.get<{
      items: IMMessage[];
      total: number;
      page: number;
      pageSize: number;
    }>(`/im/conversations/${conversationId}/messages?${params}`);
  },
  send: (conversationId: string, content: string, msgType = 7) =>
    http.post<IMMessage>(`/im/conversations/${conversationId}/send`, {
      content,
      msgType,
    }),
  retryMessage: (messageId: string) =>
    http.post<IMMessage>(`/im/messages/${messageId}/retry`),
  takeOverMessage: (messageId: string) =>
    http.post<IMMessage>(`/im/messages/${messageId}/takeover`),
  markRead: (conversationId: string) =>
    http.put<void>(`/im/conversations/${conversationId}/read`),
  rules: () => http.get<IMAutoReplyRule[]>("/im/rules"),
  createRule: (data: Partial<IMAutoReplyRule>) =>
    http.post<IMAutoReplyRule>("/im/rules", data),
  updateRule: (id: string, data: Partial<IMAutoReplyRule>) =>
    http.put<IMAutoReplyRule>(`/im/rules/${id}`, data),
  deleteRule: (id: string) => http.delete<void>(`/im/rules/${id}`),
  toggleRule: (id: string) =>
    http.put<IMAutoReplyRule>(`/im/rules/${id}/toggle`),
  listenerStatus: () => http.get<IMListenerStatus[]>("/im/listener/status"),
  startListener: (accountId: string) =>
    http.post<IMListenerStatus>("/im/listener/start", { accountId }),
  stopListener: (accountId: string) =>
    http.post<IMListenerStatus>("/im/listener/stop", { accountId }),
  automationStatus: () =>
    http.get<IMAutomationStatus[]>("/im/automation/status"),
  authorizeAutomation: (accountId: string) =>
    http.post<IMAutomationStatus>("/im/automation/authorize", {
      accountId,
      accepted: true,
      riskVersion: "im-auto-reply-v1",
    }),
  disableAutomation: (accountId: string) =>
    http.post<IMAutomationStatus>(`/im/automation/${accountId}/disable`),
};

// ---------- dashboard ----------
export const dashboardApi = {
  overview: () => http.get<DashboardOverview>("/dashboard/overview"),
  feed: () => http.get<FeedEvent[]>("/dashboard/feed"),
};
