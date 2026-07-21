"""im 模块 Pydantic schemas（出入参）"""

from pydantic import BaseModel

# ---- 会话 ----


class ConversationOut(BaseModel):
    id: str
    accountId: str
    platform: str
    remoteUid: str
    remoteNickname: str
    remoteAvatar: str
    lastMessageAt: str
    unreadCount: int
    status: str
    createdAt: str


class ConversationPageOut(BaseModel):
    items: list[ConversationOut]
    total: int
    page: int
    pageSize: int


# ---- 消息 ----


class MessageOut(BaseModel):
    id: str
    conversationId: str
    direction: str
    msgType: int
    content: str
    autoReplied: bool
    replyContent: str
    sendStatus: str
    sendError: str
    retryCount: int
    manualTakeover: bool
    moderationStatus: str
    moderationReason: str
    createdAt: str


class MessagePageOut(BaseModel):
    items: list[MessageOut]
    total: int
    page: int
    pageSize: int


class SendMessageIn(BaseModel):
    content: str
    msgType: int = 7  # 默认文本


# ---- 自动回复规则 ----


class RuleCreateIn(BaseModel):
    accountId: str = ""
    name: str
    triggerType: str = "all"  # keyword | all | llm
    triggerPattern: str = ""
    replyMode: str = "template"  # template | llm
    replyTemplate: str = ""
    llmPrompt: str = ""
    priority: int = 100
    dailyLimit: int = 50
    delayMin: int = 3
    delayMax: int = 30
    deliveryMode: str = "suggestion"
    enabled: bool = True


class RuleUpdateIn(BaseModel):
    name: str | None = None
    triggerType: str | None = None
    triggerPattern: str | None = None
    replyMode: str | None = None
    replyTemplate: str | None = None
    llmPrompt: str | None = None
    priority: int | None = None
    dailyLimit: int | None = None
    delayMin: int | None = None
    delayMax: int | None = None
    deliveryMode: str | None = None
    enabled: bool | None = None


class RuleOut(BaseModel):
    id: str
    accountId: str
    name: str
    triggerType: str
    triggerPattern: str
    replyMode: str
    replyTemplate: str
    llmPrompt: str
    priority: int
    dailyLimit: int
    delayMin: int
    delayMax: int
    deliveryMode: str
    enabled: bool
    createdAt: str


# ---- 监听状态 ----


class ListenerStatusOut(BaseModel):
    accountId: str
    accountNickname: str = ""
    platform: str = "douyin"
    status: str  # listening | disconnected | error
    lastHeartbeat: str | None = None
    errorMsg: str = ""
    startedAt: str | None = None


class ListenerControlIn(BaseModel):
    accountId: str
