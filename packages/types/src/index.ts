/**
 * 口播IP智能体共享类型（对齐 06 文档 §9.3 PipelineTask 统一模型 / §10.2 流水线引擎）
 * 契约同源：与后端 Pydantic schemas 一一对应，由 OpenAPI 生成校验。
 */

// ============ 基础枚举 ============

/** 平台 */
export type Platform = "douyin" | "kuaishou" | "xiaohongshu" | "shipinhao";

export const PLATFORM_NAMES: Record<Platform, string> = {
  douyin: "抖音",
  kuaishou: "快手",
  xiaohongshu: "小红书",
  shipinhao: "视频号",
};

/** 支持账号绑定与发布的平台（快手仅支持链接解析去水印，不可绑定发布） */
export const PUBLISH_PLATFORMS: Platform[] = [
  "douyin",
  "xiaohongshu",
  "shipinhao",
];

/** 算力通道（MVP 恒为 cloud；V1.5+ 本地引擎开放后出现 local） */
export type ComputeChannel = "cloud" | "local";

/** 流水线步骤（STEP_ORDER，8 步；edit 在自动模式可跳过） */
export type PipelineStep =
  | "parse"
  | "asr"
  | "rewrite"
  | "voice"
  | "avatar"
  | "compose"
  | "edit"
  | "publish";

export const STEP_ORDER: readonly PipelineStep[] = [
  "parse",
  "asr",
  "rewrite",
  "voice",
  "avatar",
  "compose",
  "edit",
  "publish",
] as const;

/** 步骤中文标签（UI 7 步向导 / flow-bar 共用） */
export const STEP_LABELS: Record<PipelineStep, string> = {
  parse: "链接/选题",
  asr: "转写",
  rewrite: "文案",
  voice: "声音",
  avatar: "数字人",
  compose: "合成",
  edit: "剪辑",
  publish: "发布",
};

/** 步骤状态 */
export type StepStatus =
  "pending" | "running" | "done" | "failed" | "skipped" | "waiting_confirm";

/** 任务状态机：PENDING → RUNNING → DONE / FAILED / CANCELED */
export type TaskStatus =
  "pending" | "running" | "done" | "failed" | "canceled" | "waiting_confirm";

/** 流水线模式：auto 全自动 / manual 每步暂停可干预（F-405） */
export type PipelineMode = "auto" | "manual";

// ============ 用户与计费 ============

export interface User {
  id: string;
  phone: string;
  nickname: string;
  avatarChar: string;
  createdAt: string;
  planType?: string;
  planExpiresAt?: string | null;
  activatedAt?: string | null;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

export interface Quota {
  balance: number;
  usedThisMonth: number;
  total: number;
}

export interface QuotaUsageItem {
  id: string;
  traceId: string;
  step: PipelineStep;
  resolution: string;
  points: number;
  compute: ComputeChannel;
  createdAt: string;
}

export type PlanSkuType =
  "trial" | "annual_bundle" | "internal_annual" | "points_pack";
export type PlanAudience = "public" | "internal";
export type BillingUnit =
  | "per_action"
  | "per_minute"
  | "per_second"
  | "per_1k_chars"
  | "per_1k_tokens"
  | "per_image"
  | "per_asset";

export interface PlanSku {
  code: string;
  version: number;
  skuType: PlanSkuType;
  audience: PlanAudience;
  name: string;
  subtitle?: string | null;
  description?: string | null;
  badge?: string | null;
  sortOrder?: number;
  durationDays: number;
  monthlyPoints: number;
  oneTimePoints: number;
  listPriceCents?: number | null;
  displayPriceCents?: number | null;
  entitlements: string[];
  maxConcurrency?: number | null;
  maxResolution?: string | null;
  purchaseInstructions?: string | null;
  publishedAt?: string | null;
  retiredAt?: string | null;
}

export interface ModulePrice {
  module: string;
  displayName: string;
  publicDescription?: string | null;
  billingUnit: BillingUnit;
  unitSize: number;
  pointsPerUnit: number;
  minimumPoints: number;
}

export interface ModulePriceCatalog {
  version: string;
  updatedAt?: string;
  items: ModulePrice[];
}

export interface PricePreviewItem {
  module: string;
  name?: string;
  quantity: number;
  unit: BillingUnit;
  points: number;
}

export interface PricePreviewRequest {
  items: Array<{
    module: string;
    quantity: number;
  }>;
}

export interface PricePreview {
  quoteId: string;
  priceVersion: string;
  expiresAt: string;
  items: PricePreviewItem[];
  estimatedPoints: number;
  availablePoints: number;
}

export interface Subscription {
  planType: string;
  planSkuCode?: string | null;
  planName?: string | null;
  planExpiresAt: string | null;
  activatedAt: string | null;
  nextGrantAt?: string | null;
  monthlyPoints?: number;
  quotaBalance: number;
}

// ============ IP 资产 ============

export interface Persona {
  id: string;
  name: string;
  domain: string;
  tone: string;
  values: string;
  tabooWords: string[];
  avatarChar: string;
  avatarGrad: string;
  voiceId?: string | null;
  avatarId?: string | null;
  isActive: boolean;
  // 三阶段仿写引擎扩展字段
  audience: string;
  contentPillars: string[];
  styleSamples: string;
  catchphrase: string;
  videoDuration: number;
  ctaStyle: string;
  avoidTopics: string[];
}

export type VoiceStatus =
  "ready" | "training" | "pending_confirm" | "rejected" | "failed";

export interface Voice {
  id: string;
  name: string;
  source: "clone" | "builtin";
  provider: string;
  gender: string;
  emotion: string;
  sampleUrl?: string | null;
  demoUrl?: string | null;
  status: VoiceStatus;
  createdAt: string;
}

export interface Avatar {
  id: string;
  name: string;
  source: "clone" | "public";
  provider: string;
  style?: string;
  coverUrl?: string | null;
  previewUrl?: string | null;
  status: "ready" | "training" | "failed";
  createdAt: string;
}

// ============ 内容（文案） ============

/** 字级时间戳（ASR/TTS 双模式字幕基础，C3/C4） */
export interface WordTimestamp {
  word: string;
  start: number;
  end: number;
}

export interface Transcript {
  text: string;
  words: WordTimestamp[];
  duration: number;
  language: string;
}

export interface ParseResult {
  transcript?: Transcript | null;
  degraded: boolean;
  platform?: Platform | null;
  title?: string | null;
  scriptId?: string | null;
}

export interface SimilarityResult {
  score: number;
  duplicatedSpans: { text: string; start: number; end: number }[];
}

export type RewriteIntensity = "light" | "structure" | "theme";

/** 三阶段仿写引擎返回结果 */
export interface RewriteResult {
  text: string;
  structure?: Record<string, unknown> | null;
  outline?: string | null;
  similarity?: number | null;
  validationPassed: boolean;
}

/** 文案资产（文案工坊） */
export interface Script {
  id: string;
  title: string;
  sourceUrl: string;
  platform: string;
  originalText: string;
  rewrittenText: string;
  similarityScore: number;
  status: string;
  createdAt: string;
}

// ============ 流水线任务 ============

export interface StepState {
  step: PipelineStep;
  status: StepStatus;
  progress: number;
  message?: string;
  compute?: ComputeChannel;
  provider?: string;
  quotaCost?: number;
  artifacts?: Record<string, string>;
  startedAt?: string | null;
  finishedAt?: string | null;
  durationMs?: number | null;
}

/** 统一任务模型（任务卡 / 详情 / 推送共用） */
export interface PipelineTask {
  id: string;
  ipId: string;
  title: string;
  coverUrl?: string | null;
  sourceUrl?: string;
  mode: PipelineMode;
  status: TaskStatus;
  steps: StepState[];
  currentStep?: PipelineStep | null;
  compute: ComputeChannel;
  quotaCost: number;
  error?: string;
  artifacts?: Record<string, unknown>;
  batchId?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface TaskStats {
  todayDone: number;
  todayDelta: number;
  queued: number;
  published: number;
  weekDelta: number;
  pendingAlerts: number;
}

// ============ 发布 ============

export type PublishStatus =
  "queued" | "publishing" | "success" | "failed" | "export_ready";

export interface PublishCapability {
  platform: Platform;
  platformName: string;
  mode: "automatic" | "semi_automatic" | "export_only" | "development_mock";
  verificationStatus: "verified" | "unverified" | "development_mock";
  automaticEnabled: boolean;
  fallback: "manual_package";
  reason: string;
}

export interface PublishAccount {
  id: string;
  platform: Platform;
  platformName: string;
  nickname: string;
  status: "active" | "expired";
  createdAt: string;
}

export interface PublishJob {
  id: string;
  taskId: string;
  platform: Platform;
  platformName: string;
  accountId: string;
  accountNickname: string;
  title: string;
  status: PublishStatus;
  scheduledAt?: string | null;
  error: string;
  postId: string;
  videoUrl?: string | null;
  packageUrl?: string | null;
  retryCount: number;
  createdAt: string;
  updatedAt: string;
}

// ============ 通知 / 事件 ============

export interface FeedEvent {
  id: string;
  type: "ok" | "err" | "info" | "run";
  text: string;
  link?: string;
  createdAt: string;
}

export interface Notification {
  id: string;
  level: "info" | "warn" | "error";
  title: string;
  body: string;
  read: boolean;
  createdAt: string;
}

export interface DashboardOverview extends TaskStats {
  quotaBalance: number;
  quotaUsed: number;
}

// ============ API 通用 ============

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ApiError {
  code: string;
  message: string;
}
