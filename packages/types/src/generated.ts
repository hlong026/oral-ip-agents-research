/**
 * 由后端 OpenAPI 契约自动生成（scripts/gen-api-types.mjs）
 * API 版本：1.0.0 · 生成时间：2026-07-24T13:58:57.419Z
 * 禁止手改：每次后端发版执行 pnpm gen:api 重新生成，CI 以 --check 校验零漂移。
 */

export interface AccountOut {
  id: string;
  platform: string;
  platformName: string;
  nickname: string;
  status: string;
  createdAt: string;
}

export interface AccountUpdateIn {
  nickname: string;
}

export interface ActivateIn {
  code: string;
  phone: string;
  password: string;
  nickname?: string;
  deviceFingerprint?: string;
}

export interface ActivateOut {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  planType: string;
  planSkuCode?: string;
  planExpiresAt?: string | null;
  quotaBalance?: number;
}

export interface AutomationConsentIn {
  accountId: string;
  accepted: boolean;
  riskVersion: string;
}

export interface AutomationStatusOut {
  accountId: string;
  authorized: boolean;
  riskVersion?: string;
  acceptedAt?: string | null;
}

export interface AvatarOut {
  id: string;
  name: string;
  source: string;
  avatarType: string;
  scene: string;
  style: string;
  coverUrl: string | null;
  previewUrl?: string | null;
  status: string;
  createdAt: string;
}

export interface AvatarStatusOut {
  id: string;
  status: string;
  progress?: number;
}

export interface BatchCreateIn {
  name?: string;
  skuVersionId: string;
  planType?: string;
  quotaAmount?: number;
  durationDays?: number;
  count?: number;
  channel?: string;
  codeExpiresAt?: string | null;
}

export interface BatchGenerateOut {
  batchId: string;
  generated: number;
  codes: string[];
}

export interface BatchRewriteIn {
  text: string;
  intensity?: string;
  count?: number;
  prompt?: string | null;
  scriptId?: string | null;
  quoteId?: string | null;
}

export interface BatchRewriteItemOut {
  text: string;
  similarity: number;
  strategy: string;
  providerName: string;
}

export interface BatchRewriteOut {
  items: BatchRewriteItemOut[];
  structure: Record<string, unknown>;
  outline: string;
}

export interface Body_api_clone_api_v1_voices_clone_post {
  name: string;
  consentToken: string;
  language?: string;
  quoteId?: string | null;
  file: string;
}

export interface Body_api_clone_image_api_v1_avatars_create_by_image_post {
  name: string;
  consentToken: string;
  scene?: string;
  quoteId?: string | null;
  file: string;
}

export interface Body_api_clone_video_api_v1_avatars_clone_post {
  name: string;
  consentToken: string;
  scene?: string;
  quoteId?: string | null;
  file: string;
  cover?: string | null;
}

export interface Body_api_parse_api_v1_content_parse_post {
  body?: string | null;
  url?: string | null;
  quoteId?: string | null;
  file?: string | null;
}

export interface Body_api_submit_parse_job_api_v1_content_jobs_parse_post {
  url?: string | null;
  quoteId?: string | null;
  file?: string | null;
}

export interface CloneStatusOut {
  id: string;
  status: string;
  demoUrl?: string | null;
}

export interface CodeInfoOut {
  valid: boolean;
  planType?: string;
  quotaAmount?: number;
  durationDays?: number;
  message?: string;
}

export interface CodeStatsOut {
  total?: number;
  unused?: number;
  used?: number;
  expired?: number;
  revoked?: number;
}

export interface ContentJobOut {
  id: string;
  kind: string;
  status: string;
  progress: number;
  stage: string;
  result?: Record<string, unknown> | null;
  error?: string;
  createdAt: string;
  updatedAt: string;
}

export interface ConversationOut {
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

export interface ConversationPageOut {
  items: ConversationOut[];
  total: number;
  page: number;
  pageSize: number;
}

export interface CreatePipelineIn {
  ipId: string;
  sourceUrl?: string | null;
  topic?: string | null;
  scriptText?: string | null;
  voiceId?: string | null;
  avatarId?: string | null;
  mode?: string;
  intensity?: string;
  platforms?: string[];
  publishAt?: string | null;
  randomize?: boolean;
  count?: number;
  quoteId?: string | null;
}

export interface CreditAdjustIn {
  points: number;
  reason: string;
  expiresAt?: string | null;
}

export interface ExportOut {
  jobId: string;
  videoUrl: string;
  packageKey: string;
  packageUrl: string;
  metadata: Record<string, unknown>;
}

export interface FeedEvent {
  id: string;
  type: string;
  text: string;
  createdAt: string;
}

export interface GrayAccountOut {
  accountId: string;
  userId: string;
  nickname: string;
  approvedBy: string;
  addedAt: string;
}

export interface JobOut {
  id: string;
  taskId: string;
  platform: string;
  platformName: string;
  accountId: string;
  accountNickname?: string;
  title: string;
  status: string;
  scheduledAt?: string | null;
  error?: string;
  postId?: string;
  videoUrl?: string | null;
  packageUrl?: string | null;
  retryCount?: number;
  createdAt: string;
  updatedAt: string;
}

export interface JobPageOut {
  items: JobOut[];
  total: number;
  page: number;
  pageSize: number;
}

export interface KillSwitchIn {
  stopped: boolean;
}

export interface KillSwitchOut {
  stopped: boolean;
  canceledMessages?: number;
}

export interface ListenerControlIn {
  accountId: string;
}

export interface ListenerStatusOut {
  accountId: string;
  accountNickname?: string;
  platform?: string;
  status: string;
  lastHeartbeat?: string | null;
  errorMsg?: string;
  startedAt?: string | null;
}

export interface LoginIn {
  phone: string;
  password: string;
  deviceId?: string | null;
}

export interface MessageOut {
  id: string;
  conversationId: string;
  direction: string;
  msgType: number;
  content: string;
  autoReplied: boolean;
  replyContent: string;
  sendStatus: string;
  sendError: string;
  retryCount: number;
  manualTakeover: boolean;
  moderationStatus: string;
  moderationReason: string;
  createdAt: string;
}

export interface MessagePageOut {
  items: MessageOut[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ModulePriceCatalogOut {
  version: string;
  updatedAt?: string | null;
  items: ModulePricePublicOut[];
}

export interface ModulePriceIn {
  displayName: string;
  billingUnit:
    | "per_action"
    | "per_minute"
    | "per_second"
    | "per_1k_chars"
    | "per_1k_tokens"
    | "per_image"
    | "per_asset";
  unitSize?: number;
  pointsPerUnit?: number;
  minimumPoints?: number;
  enabled?: boolean;
  publicDescription?: string;
  internalCostCentsPerUnit?: number;
  targetMarginBps?: number;
}

export interface ModulePricePublicOut {
  module: string;
  displayName: string;
  billingUnit: string;
  unitSize: number;
  pointsPerUnit: number;
  minimumPoints: number;
  publicDescription: string;
}

export interface MonitoringIncidentIn {
  accountId?: string;
  detail: string;
}

export interface MonitoringSummaryOut {
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

export interface NotificationOut {
  id: string;
  level: string;
  title: string;
  body: string;
  read: boolean;
  createdAt: string;
}

export interface OverrideIn {
  artifacts: Record<string, string>;
}

export interface OverviewOut {
  todayDone: number;
  todayDelta: number;
  queued: number;
  published: number;
  weekDelta: number;
  pendingAlerts: number;
  quotaBalance: number;
  quotaUsed: number;
}

export interface ParseIn {
  url?: string | null;
  body?: string | null;
  videoId?: string | null;
  platform?: string | null;
  quoteId?: string | null;
}

export interface ParseOut {
  transcript: TranscriptOut | null;
  degraded: boolean;
  inputType?: string | null;
  sourceStatus?: string;
  platform?: string | null;
  title?: string | null;
  scriptId?: string | null;
  cover?: string | null;
  author?: Record<string, unknown> | null;
}

export interface PersonaIn {
  name: string;
  domain?: string;
  tone?: string;
  values?: string;
  tabooWords?: string[];
  audience?: string;
  contentPillars?: string[];
  styleSamples?: string;
  catchphrase?: string;
  videoDuration?: number;
  ctaStyle?: string;
  avoidTopics?: string[];
}

export interface PersonaOut {
  id: string;
  name: string;
  domain: string;
  tone: string;
  values: string;
  tabooWords: string[];
  avatarChar: string;
  avatarGrad: string;
  voiceId: string | null;
  avatarId: string | null;
  isActive: boolean;
  audience?: string;
  contentPillars?: string[];
  styleSamples?: string;
  catchphrase?: string;
  videoDuration?: number;
  ctaStyle?: string;
  avoidTopics?: string[];
}

export interface PersonaUpdate {
  name?: string | null;
  domain?: string | null;
  tone?: string | null;
  values?: string | null;
  tabooWords?: string[] | null;
  voiceId?: string | null;
  avatarId?: string | null;
  audience?: string | null;
  contentPillars?: string[] | null;
  styleSamples?: string | null;
  catchphrase?: string | null;
  videoDuration?: number | null;
  ctaStyle?: string | null;
  avoidTopics?: string[] | null;
}

export interface PlanCreateIn {
  code: string;
  name: string;
  subtitle?: string;
  description?: string;
  badge?: string;
  sortOrder?: number;
  skuType?: "trial" | "annual_bundle" | "internal_annual" | "points_pack";
  audience?: "public" | "internal";
  durationDays?: number;
  monthlyPoints?: number;
  oneTimePoints?: number;
  listPriceCents?: number;
  displayPriceCents?: number;
  entitlements?: string[];
  maxConcurrency?: number;
  maxResolution?: string;
  purchaseInstructions?: string;
}

export interface PlanOut {
  id: string;
  code: string;
  version: number;
  status: string;
  name: string;
  subtitle?: string;
  description?: string;
  badge?: string;
  sortOrder?: number;
  skuType: string;
  audience: string;
  durationDays: number;
  monthlyPoints: number;
  oneTimePoints: number;
  listPriceCents: number;
  displayPriceCents: number;
  entitlements: string[];
  maxConcurrency: number;
  maxResolution: string;
  purchaseInstructions?: string;
  effectiveAt?: string | null;
  publishedAt?: string | null;
  retiredAt?: string | null;
}

export interface PricePreviewIn {
  items: PricePreviewItemIn[];
}

export interface PricePreviewItemIn {
  module: string;
  quantity: number;
}

export interface PriceVersionCreateIn {
  version: string;
}

export interface PriceVersionOut {
  id: string;
  version: string;
  status: string;
  effectiveAt?: string | null;
  publishedAt?: string | null;
  retiredAt?: string | null;
}

export interface ProbeUrlIn {
  url: string;
}

export interface ProbeUrlOut {
  durationSeconds: number;
}

export interface ProviderProbeOut {
  provider: string;
  status: "verified" | "failed" | "incomplete" | "needs_sample";
  message: string;
  details?: Record<string, unknown>;
}

export interface ProviderStatusItem {
  provider: string;
  enabled: boolean;
  configured: boolean;
  missingFields: string[];
  probeMode: "credential" | "sample";
}

export interface ProviderStatusOut {
  items: ProviderStatusItem[];
}

export interface PublishCapabilityOut {
  platform: string;
  platformName: string;
  mode: string;
  verificationStatus: string;
  automaticEnabled: boolean;
  fallback?: string;
  reason?: string;
}

export interface QrcodePollOut {
  status: string;
  account?: AccountOut | null;
  qrcodeUrl?: string | null;
  message?: string | null;
}

export interface QrcodeStartOut {
  ticket: string;
  qrcodeUrl: string;
}

export interface QuotaOut {
  balance: number;
  usedThisMonth: number;
  total: number;
}

export interface RedeemIn {
  code: string;
}

export interface RedeemOut {
  planType: string;
  planSkuCode?: string;
  planExpiresAt?: string | null;
  quotaGranted?: number;
  newBalance?: number;
}

export interface RefreshIn {
  refreshToken: string;
}

export interface ReservationBatchOut {
  items: ReservationItemOut[];
  availablePoints: number;
}

export interface ReservationCreateIn {
  quoteId: string;
  count?: number;
}

export interface ReservationItemOut {
  id: string;
  quoteId: string;
  reservedPoints: number;
  status: string;
}

export interface ReservationStateOut {
  id: string;
  status: string;
  reservedPoints: number;
  actualPoints: number;
  availablePoints: number;
}

export interface RetryStepIn {
  quoteId?: string | null;
}

export interface RewriteIn {
  text: string;
  intensity?: string;
  prompt?: string | null;
  scriptId?: string | null;
  quoteId?: string | null;
}

export interface RewriteOut {
  text: string;
  structure?: Record<string, unknown> | null;
  outline?: string | null;
  similarity?: number | null;
  validationPassed?: boolean;
}

export interface RuleCreateIn {
  accountId?: string;
  name: string;
  triggerType?: string;
  triggerPattern?: string;
  replyMode?: string;
  replyTemplate?: string;
  llmPrompt?: string;
  priority?: number;
  dailyLimit?: number;
  delayMin?: number;
  delayMax?: number;
  deliveryMode?: string;
  enabled?: boolean;
}

export interface RuleOut {
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
  deliveryMode: string;
  enabled: boolean;
  createdAt: string;
}

export interface RuleUpdateIn {
  name?: string | null;
  triggerType?: string | null;
  triggerPattern?: string | null;
  replyMode?: string | null;
  replyTemplate?: string | null;
  llmPrompt?: string | null;
  priority?: number | null;
  dailyLimit?: number | null;
  delayMin?: number | null;
  delayMax?: number | null;
  deliveryMode?: string | null;
  enabled?: boolean | null;
}

export interface ScriptCreateIn {
  title?: string;
  text: string;
  platform?: string;
  topic?: string | null;
}

export interface ScriptOut {
  id: string;
  title: string;
  sourceUrl: string;
  platform: string;
  originalText: string;
  rewrittenText: string;
  similarityScore: number;
  currentVersion: number;
  modelName: string;
  promptVersion: string;
  status: string;
  createdAt: string;
}

export interface ScriptUpdateIn {
  title: string;
  text: string;
}

export interface ScriptVersionOut {
  id: string;
  version: number;
  kind: string;
  text: string;
  modelName: string;
  promptVersion: string;
  createdAt: string;
}

export interface SendMessageIn {
  content: string;
  msgType?: number;
}

export interface SettingsIn {
  settings: Record<string, string>;
}

export interface SettingsOut {
  settings: Record<string, string>;
}

export interface SimilarityIn {
  text: string;
  quoteId?: string | null;
}

export interface SimilarityOut {
  score: number;
  duplicatedSpans: SpanOut[];
}

export interface SpanOut {
  text: string;
  start: number;
  end: number;
}

export interface StatsOut {
  todayDone: number;
  queued: number;
  published: number;
  pendingAlerts: number;
  todayDelta: number;
  weekDelta: number;
}

export interface StepStateOut {
  step: string;
  status: string;
  progress: number;
  message?: string;
  compute?: string;
  provider?: string;
  quotaCost?: number;
  artifacts?: Record<string, string>;
  startedAt?: string | null;
  finishedAt?: string | null;
  durationMs?: number | null;
}

export interface SubscriptionOut {
  planType: string;
  planSkuCode?: string;
  planName?: string | null;
  planExpiresAt?: string | null;
  activatedAt?: string | null;
  nextGrantAt?: string | null;
  monthlyPoints?: number;
  quotaBalance?: number;
}

export interface SynthesizeIn {
  voiceId: string;
  text: string;
  speed?: number;
  quoteId?: string | null;
}

export interface SynthesizeOut {
  audioUrl: string;
  words: WordTsOut[];
}

export interface TaskOut {
  id: string;
  ipId: string;
  title: string;
  coverUrl?: string | null;
  sourceUrl: string;
  mode: string;
  status: string;
  steps: StepStateOut[];
  currentStep?: string | null;
  compute: string;
  quotaCost: number;
  error?: string;
  artifacts?: Record<string, unknown>;
  batchId?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface TaskPageOut {
  items: TaskOut[];
  total: number;
  page: number;
  pageSize: number;
}

export interface TokensOut {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

export interface TopicsIn {
  keyword: string;
  quoteId?: string | null;
}

export interface TopicsOut {
  topics: string[];
}

export interface TranscriptOut {
  text: string;
  words: WordTsOut[];
  duration: number;
  language?: string;
}

export interface UnreadOut {
  count: number;
}

export interface UserOut {
  id: string;
  phone: string;
  nickname: string;
  avatarChar: string;
  createdAt: string;
  planType?: string;
  planExpiresAt?: string | null;
  activatedAt?: string | null;
}

export interface UserUpdateIn {
  role?: "user" | "admin" | null;
  isActive?: boolean | null;
}

export interface ValidateCodeIn {
  code: string;
  deviceFingerprint?: string;
}

export interface VoiceEditIn {
  rate?: string;
  volume?: string;
  pitch?: string;
}

export interface VoiceOut {
  id: string;
  name: string;
  source: string;
  gender: string;
  emotion: string;
  language: string;
  sampleUrl: string | null;
  demoUrl?: string | null;
  rate?: string;
  volume?: string;
  pitch?: string;
  status: string;
  createdAt: string;
}

export interface WordTsOut {
  word: string;
  start: number;
  end: number;
}

export interface app__modules__catalog__schemas__PublishIn {
  effectiveAt?: string | null;
}

export interface app__modules__publish__schemas__PublishIn {
  taskId?: string | null;
  platforms: string[];
  title: string;
  topics?: string[];
  videoKey: string;
  coverKey?: string | null;
  publishAt?: string | null;
}
