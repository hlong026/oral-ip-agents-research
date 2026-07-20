/**
 * 由后端 OpenAPI 契约自动生成（scripts/gen-api-types.mjs）
 * API 版本：1.0.0 · 生成时间：2026-07-20T00:47:43.814Z
 * 禁止手改：每次后端发版执行 pnpm gen:api 重新生成，CI 以 --check 校验零漂移。
 */

export interface AccountOut {
  "id": string;
  "platform": string;
  "platformName": string;
  "nickname": string;
  "status": string;
  "createdAt": string;
}

export interface AvatarOut {
  "id": string;
  "name": string;
  "source": string;
  "avatarType": string;
  "scene": string;
  "style": string;
  "coverUrl": string | null;
  "previewUrl"?: string | null;
  "status": string;
  "createdAt": string;
}

export interface AvatarStatusOut {
  "id": string;
  "status": string;
  "progress"?: number;
}

export interface Body_api_clone_api_v1_voices_clone_post {
  "name": string;
  "consentToken": string;
  "language"?: string;
  "file": string;
}

export interface Body_api_clone_image_api_v1_avatars_create_by_image_post {
  "name": string;
  "consentToken": string;
  "scene"?: string;
  "file": string;
}

export interface Body_api_clone_video_api_v1_avatars_clone_post {
  "name": string;
  "consentToken": string;
  "scene"?: string;
  "file": string;
  "cover"?: string | null;
}

export interface Body_api_parse_api_v1_content_parse_post {
  "body"?: string | null;
  "url"?: string | null;
  "file"?: string | null;
}

export interface CloneStatusOut {
  "id": string;
  "status": string;
  "demoUrl"?: string | null;
}

export interface ConversationOut {
  "id": string;
  "accountId": string;
  "platform": string;
  "remoteUid": string;
  "remoteNickname": string;
  "remoteAvatar": string;
  "lastMessageAt": string;
  "unreadCount": number;
  "status": string;
  "createdAt": string;
}

export interface ConversationPageOut {
  "items": ConversationOut[];
  "total": number;
  "page": number;
  "pageSize": number;
}

export interface CreatePipelineIn {
  "ipId": string;
  "sourceUrl"?: string | null;
  "topic"?: string | null;
  "scriptText"?: string | null;
  "voiceId"?: string | null;
  "avatarId"?: string | null;
  "mode"?: string;
  "platforms"?: string[];
  "publishAt"?: string | null;
  "randomize"?: boolean;
  "count"?: number;
}

export interface ExportOut {
  "jobId": string;
  "videoUrl": string;
}

export interface FeedEvent {
  "id": string;
  "type": string;
  "text": string;
  "createdAt": string;
}

export interface JobOut {
  "id": string;
  "taskId": string;
  "platform": string;
  "platformName": string;
  "accountId": string;
  "accountNickname"?: string;
  "title": string;
  "status": string;
  "scheduledAt"?: string | null;
  "error"?: string;
  "postId"?: string;
  "videoUrl"?: string | null;
  "retryCount"?: number;
  "createdAt": string;
  "updatedAt": string;
}

export interface JobPageOut {
  "items": JobOut[];
  "total": number;
  "page": number;
  "pageSize": number;
}

export interface ListenerControlIn {
  "accountId": string;
}

export interface ListenerStatusOut {
  "accountId": string;
  "accountNickname"?: string;
  "platform"?: string;
  "status": string;
  "lastHeartbeat"?: string | null;
  "errorMsg"?: string;
  "startedAt"?: string | null;
}

export interface LoginIn {
  "phone": string;
  "password": string;
  "deviceId"?: string | null;
}

export interface MessageOut {
  "id": string;
  "conversationId": string;
  "direction": string;
  "msgType": number;
  "content": string;
  "autoReplied": boolean;
  "replyContent": string;
  "createdAt": string;
}

export interface MessagePageOut {
  "items": MessageOut[];
  "total": number;
  "page": number;
  "pageSize": number;
}

export interface NotificationOut {
  "id": string;
  "level": string;
  "title": string;
  "body": string;
  "read": boolean;
  "createdAt": string;
}

export interface OverrideIn {
  "artifacts": Record<string, string>;
}

export interface OverviewOut {
  "todayDone": number;
  "todayDelta": number;
  "queued": number;
  "published": number;
  "weekDelta": number;
  "pendingAlerts": number;
  "quotaBalance": number;
  "quotaUsed": number;
}

export interface ParseIn {
  "url"?: string | null;
  "videoId"?: string | null;
  "platform"?: string | null;
}

export interface ParseOut {
  "transcript": TranscriptOut | null;
  "degraded": boolean;
  "platform"?: string | null;
  "title"?: string | null;
  "scriptId"?: string | null;
  "cover"?: string | null;
  "author"?: Record<string, unknown> | null;
}

export interface PersonaIn {
  "name": string;
  "domain"?: string;
  "tone"?: string;
  "values"?: string;
  "tabooWords"?: string[];
  "audience"?: string;
  "contentPillars"?: string[];
  "styleSamples"?: string;
  "catchphrase"?: string;
  "videoDuration"?: number;
  "ctaStyle"?: string;
  "avoidTopics"?: string[];
}

export interface PersonaOut {
  "id": string;
  "name": string;
  "domain": string;
  "tone": string;
  "values": string;
  "tabooWords": string[];
  "avatarChar": string;
  "avatarGrad": string;
  "voiceId": string | null;
  "avatarId": string | null;
  "isActive": boolean;
  "audience"?: string;
  "contentPillars"?: string[];
  "styleSamples"?: string;
  "catchphrase"?: string;
  "videoDuration"?: number;
  "ctaStyle"?: string;
  "avoidTopics"?: string[];
}

export interface PersonaUpdate {
  "name"?: string | null;
  "domain"?: string | null;
  "tone"?: string | null;
  "values"?: string | null;
  "tabooWords"?: string[] | null;
  "voiceId"?: string | null;
  "avatarId"?: string | null;
  "audience"?: string | null;
  "contentPillars"?: string[] | null;
  "styleSamples"?: string | null;
  "catchphrase"?: string | null;
  "videoDuration"?: number | null;
  "ctaStyle"?: string | null;
  "avoidTopics"?: string[] | null;
}

export interface PublishIn {
  "taskId"?: string | null;
  "platforms": string[];
  "title": string;
  "topics"?: string[];
  "videoKey": string;
  "coverKey"?: string | null;
  "publishAt"?: string | null;
}

export interface QrcodePollOut {
  "status": string;
  "account"?: AccountOut | null;
}

export interface QrcodeStartOut {
  "ticket": string;
  "qrcodeUrl": string;
}

export interface QuotaOut {
  "balance": number;
  "usedThisMonth": number;
  "total": number;
}

export interface RefreshIn {
  "refreshToken": string;
}

export interface RegisterIn {
  "phone": string;
  "password": string;
  "nickname"?: string;
}

export interface RewriteIn {
  "text": string;
  "intensity"?: string;
  "prompt"?: string | null;
  "scriptId"?: string | null;
}

export interface RewriteOut {
  "text": string;
  "structure"?: Record<string, unknown> | null;
  "outline"?: string | null;
  "similarity"?: number | null;
  "validationPassed"?: boolean;
}

export interface RuleCreateIn {
  "accountId"?: string;
  "name": string;
  "triggerType"?: string;
  "triggerPattern"?: string;
  "replyMode"?: string;
  "replyTemplate"?: string;
  "llmPrompt"?: string;
  "priority"?: number;
  "dailyLimit"?: number;
  "delayMin"?: number;
  "delayMax"?: number;
  "enabled"?: boolean;
}

export interface RuleOut {
  "id": string;
  "accountId": string;
  "name": string;
  "triggerType": string;
  "triggerPattern": string;
  "replyMode": string;
  "replyTemplate": string;
  "llmPrompt": string;
  "priority": number;
  "dailyLimit": number;
  "delayMin": number;
  "delayMax": number;
  "enabled": boolean;
  "createdAt": string;
}

export interface RuleUpdateIn {
  "name"?: string | null;
  "triggerType"?: string | null;
  "triggerPattern"?: string | null;
  "replyMode"?: string | null;
  "replyTemplate"?: string | null;
  "llmPrompt"?: string | null;
  "priority"?: number | null;
  "dailyLimit"?: number | null;
  "delayMin"?: number | null;
  "delayMax"?: number | null;
  "enabled"?: boolean | null;
}

export interface ScriptCreateIn {
  "title"?: string;
  "text": string;
  "platform"?: string;
  "topic"?: string | null;
}

export interface ScriptOut {
  "id": string;
  "title": string;
  "sourceUrl": string;
  "platform": string;
  "originalText": string;
  "rewrittenText": string;
  "similarityScore": number;
  "status": string;
  "createdAt": string;
}

export interface SendMessageIn {
  "content": string;
  "msgType"?: number;
}

export interface SettingsIn {
  "settings": Record<string, string>;
}

export interface SettingsOut {
  "settings": Record<string, string>;
}

export interface SimilarityIn {
  "text": string;
}

export interface SimilarityOut {
  "score": number;
  "duplicatedSpans": SpanOut[];
}

export interface SpanOut {
  "text": string;
  "start": number;
  "end": number;
}

export interface StatsOut {
  "todayDone": number;
  "queued": number;
  "published": number;
  "pendingAlerts": number;
  "todayDelta": number;
  "weekDelta": number;
}

export interface StepStateOut {
  "step": string;
  "status": string;
  "progress": number;
  "message"?: string;
  "compute"?: string;
  "provider"?: string;
  "quotaCost"?: number;
  "artifacts"?: Record<string, string>;
  "startedAt"?: string | null;
  "finishedAt"?: string | null;
}

export interface SynthesizeIn {
  "voiceId": string;
  "text": string;
  "speed"?: number;
}

export interface SynthesizeOut {
  "audioUrl": string;
  "words": WordTsOut[];
}

export interface TaskOut {
  "id": string;
  "ipId": string;
  "title": string;
  "coverUrl"?: string | null;
  "sourceUrl": string;
  "mode": string;
  "status": string;
  "steps": StepStateOut[];
  "currentStep"?: string | null;
  "compute": string;
  "quotaCost": number;
  "batchId"?: string | null;
  "createdAt": string;
  "updatedAt": string;
}

export interface TaskPageOut {
  "items": TaskOut[];
  "total": number;
  "page": number;
  "pageSize": number;
}

export interface TokensOut {
  "accessToken": string;
  "refreshToken": string;
  "expiresIn": number;
}

export interface TopicsIn {
  "keyword": string;
}

export interface TopicsOut {
  "topics": string[];
}

export interface TranscriptOut {
  "text": string;
  "words": WordTsOut[];
  "duration": number;
  "language"?: string;
}

export interface UnreadOut {
  "count": number;
}

export interface UserOut {
  "id": string;
  "phone": string;
  "nickname": string;
  "avatarChar": string;
  "createdAt": string;
}

export interface VoiceEditIn {
  "rate"?: string;
  "volume"?: string;
  "pitch"?: string;
}

export interface VoiceOut {
  "id": string;
  "name": string;
  "source": string;
  "gender": string;
  "emotion": string;
  "language": string;
  "sampleUrl": string | null;
  "demoUrl"?: string | null;
  "rate"?: string;
  "volume"?: string;
  "pitch"?: string;
  "status": string;
  "createdAt": string;
}

export interface WordTsOut {
  "word": string;
  "start": number;
  "end": number;
}
