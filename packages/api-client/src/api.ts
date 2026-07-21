/**
 * API 端点封装（对齐后端 FastAPI 路由，契约同源）
 */
import type {
  AuthTokens,
  Avatar,
  DashboardOverview,
  FeedEvent,
  Notification,
  Page,
  ParseResult,
  Persona,
  PipelineMode,
  PipelineTask,
  Platform,
  PublishAccount,
  PublishJob,
  Quota,
  QuotaUsageItem,
  RewriteIntensity,
  RewriteResult,
  Script,
  SimilarityResult,
  TaskStats,
  User,
  Voice,
  WordTimestamp,
} from "@oral/types";
import { http } from "./http";

// ---------- auth ----------
export const authApi = {
  register: (phone: string, password: string, nickname: string) =>
    http.post<AuthTokens>("/auth/register", { phone, password, nickname }),
  login: (phone: string, password: string, deviceId?: string) =>
    http.post<AuthTokens>("/auth/login", { phone, password, deviceId }),
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

export interface ActivateResult {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  planType: string;
  planExpiresAt: string | null;
  quotaBalance: number;
}

export interface RedeemResult {
  planType: string;
  planExpiresAt: string | null;
  quotaGranted: number;
  newBalance: number;
}

export interface SubscriptionInfo {
  planType: string;
  planExpiresAt: string | null;
  activatedAt: string | null;
  quotaBalance: number;
}

export const activationApi = {
  validateCode: (code: string) =>
    http.post<CodeInfo>("/activation/validate-code", { code }),
  activate: (code: string, phone: string, password: string, nickname: string, deviceFingerprint = "web") =>
    http.post<ActivateResult>("/activation/activate", { code, phone, password, nickname, deviceFingerprint }),
  redeem: (code: string) =>
    http.post<RedeemResult>("/activation/redeem", { code }),
  subscription: () => http.get<SubscriptionInfo>("/activation/subscription"),
};

// ---------- billing ----------
export const billingApi = {
  quota: () => http.get<Quota>("/billing/quota"),
  usage: (page = 1, pageSize = 20) =>
    http.get<Page<QuotaUsageItem>>(`/billing/usage?page=${page}&pageSize=${pageSize}`),
  exportCsvUrl: () => `/api/v1/billing/usage?export=csv`,
};

// ---------- personas / ipasset ----------
export const personaApi = {
  list: () => http.get<Persona[]>("/personas"),
  get: (id: string) => http.get<Persona>(`/personas/${id}`),
  create: (data: Partial<Persona>) => http.post<Persona>("/personas", data),
  update: (id: string, data: Partial<Persona>) => http.put<Persona>(`/personas/${id}`, data),
  activate: (id: string) => http.post<Persona>(`/personas/${id}/activate`),
};

// ---------- content（文案模块 F-101~F-106） ----------
export const contentApi = {
  parse: (url?: string, file?: File): Promise<ParseResult> => {
    if (file) {
      const fd = new FormData();
      fd.append("file", file);
      return http.post<ParseResult>("/content/parse", fd);
    }
    const fd = new FormData();
    if (url) fd.append("url", url);
    return http.post<ParseResult>("/content/parse", fd);
  },
  rewrite: (text: string, intensity: RewriteIntensity, prompt?: string, scriptId?: string) =>
    http.post<RewriteResult>("/content/rewrite", { text, intensity, prompt, scriptId }),
  similarity: (text: string) => http.post<SimilarityResult>("/content/similarity", { text }),
  topics: (keyword: string) => http.post<{ topics: string[] }>("/content/topics", { keyword }),
  scripts: () => http.get<Script[]>("/content/scripts"),
  script: (id: string) => http.get<Script>(`/content/scripts/${id}`),
  createScript: (input: { title?: string; text: string; platform?: string; topic?: string }) =>
    http.post<Script>("/content/scripts", input),
};

// ---------- voices / avatars（克隆强制 consent_token；绑定 IP 走 personaApi.update） ----------
export const voiceApi = {
  list: () => http.get<Voice[]>("/voices"),
  clone: (name: string, consentToken: string, file: File) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("consentToken", consentToken);
    fd.append("file", file);
    return http.post<Voice>("/voices/clone", fd);
  },
  synthesize: (voiceId: string, text: string, speed = 1.0) =>
    http.post<{ audioUrl: string; words: WordTimestamp[] }>(
      "/voices/synthesize",
      { voiceId, text, speed },
    ),
};

export const avatarApi = {
  list: () => http.get<Avatar[]>("/avatars"),
  clone: (name: string, consentToken: string, file: File) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("consentToken", consentToken);
    fd.append("file", file);
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
}

export const pipelineApi = {
  create: (input: CreatePipelineInput) => http.post<PipelineTask[]>("/pipelines", input),
  list: (status?: string, page = 1, pageSize = 20) =>
    http.get<Page<PipelineTask>>(
      `/pipelines?page=${page}&pageSize=${pageSize}${status ? `&status=${status}` : ""}`,
    ),
  get: (id: string) => http.get<PipelineTask>(`/pipelines/${id}`),
  retryStep: (id: string, step: string) => http.post<PipelineTask>(`/pipelines/${id}/steps/${step}/retry`),
  overrideStep: (id: string, step: string, artifacts: Record<string, string>) =>
    http.post<PipelineTask>(`/pipelines/${id}/steps/${step}/override`, { artifacts }),
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
  accounts: () => http.get<PublishAccount[]>("/publish/accounts"),
  qrcodeStart: (platform: Platform) =>
    http.post<{ ticket: string; qrcodeUrl: string }>(`/publish/accounts/qrcode?platform=${platform}`),
  qrcodePoll: (ticket: string, platform: Platform) =>
    http.get<{ status: "waiting" | "success" | "expired"; account?: PublishAccount | null; qrcodeUrl?: string | null }>(
      `/publish/accounts/qrcode/${ticket}?platform=${platform}`,
    ),
  reauth: (accountId: string) =>
    http.post<{ ticket: string; qrcodeUrl: string }>(`/publish/accounts/${accountId}/reauth`),
  deleteAccount: (accountId: string) => http.delete<void>(`/publish/accounts/${accountId}`),
  renameAccount: (accountId: string, nickname: string) =>
    http.patch<PublishAccount>(`/publish/accounts/${accountId}`, { nickname }),
  jobs: (status?: string, page = 1, pageSize = 20) =>
    http.get<Page<PublishJob>>(
      `/publish/jobs?page=${page}&pageSize=${pageSize}${status ? `&status=${status}` : ""}`,
    ),
  logs: (page = 1, pageSize = 50) => http.get<Page<PublishJob>>(`/publish/logs?page=${page}&pageSize=${pageSize}`),
  createJobs: (input: CreatePublishInput) => http.post<PublishJob[]>("/publish/jobs", input),
  retryJob: (jobId: string) => http.post<PublishJob>(`/publish/jobs/${jobId}/retry`),
  exportJob: (jobId: string) => http.post<{ jobId: string; videoUrl: string }>(`/publish/jobs/${jobId}/export`),
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

export const imApi = {
  conversations: (page = 1, pageSize = 20) =>
    http.get<{ items: IMConversation[]; total: number; page: number; pageSize: number }>(
      `/im/conversations?page=${page}&pageSize=${pageSize}`,
    ),
  messages: (conversationId: string, page = 1, pageSize = 50) =>
    http.get<{ items: IMMessage[]; total: number; page: number; pageSize: number }>(
      `/im/conversations/${conversationId}/messages?page=${page}&pageSize=${pageSize}`,
    ),
  send: (conversationId: string, content: string, msgType = 7) =>
    http.post<IMMessage>(`/im/conversations/${conversationId}/send`, { content, msgType }),
  markRead: (conversationId: string) =>
    http.put<void>(`/im/conversations/${conversationId}/read`),
  rules: () => http.get<IMAutoReplyRule[]>("/im/rules"),
  createRule: (data: Partial<IMAutoReplyRule>) => http.post<IMAutoReplyRule>("/im/rules", data),
  updateRule: (id: string, data: Partial<IMAutoReplyRule>) =>
    http.put<IMAutoReplyRule>(`/im/rules/${id}`, data),
  deleteRule: (id: string) => http.delete<void>(`/im/rules/${id}`),
  toggleRule: (id: string) => http.put<IMAutoReplyRule>(`/im/rules/${id}/toggle`),
  listenerStatus: () => http.get<IMListenerStatus[]>("/im/listener/status"),
  startListener: (accountId: string) =>
    http.post<IMListenerStatus>("/im/listener/start", { accountId }),
  stopListener: (accountId: string) =>
    http.post<IMListenerStatus>("/im/listener/stop", { accountId }),
};

// ---------- dashboard ----------
export const dashboardApi = {
  overview: () => http.get<DashboardOverview>("/dashboard/overview"),
  feed: () => http.get<FeedEvent[]>("/dashboard/feed"),
};

// ---------- settings（Provider 配置） ----------
export const settingsApi = {
  get: () => http.get<{ settings: Record<string, string> }>("/settings"),
  save: (settings: Record<string, string>) =>
    http.put<{ settings: Record<string, string> }>("/settings", { settings }),
};
