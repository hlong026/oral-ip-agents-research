"""Deterministic safety checks for IM suggestions and outbound replies."""

import re
from dataclasses import dataclass

_SENSITIVE_TERMS = ("赌博", "博彩", "毒品", "枪支", "代开发票")
_PROMISE_TERMS = ("保证收益", "稳赚不赔", "百分百有效", "绝对安全", "包治", "保证效果")
_CONTACT_PATTERNS = (
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?:加|联系)?(?:微信|微.?信|vx|v信|QQ|扣扣)", re.IGNORECASE),
    re.compile(r"https?://|www\.", re.IGNORECASE),
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"忽略(?:之前|以上|所有).{0,12}(?:指令|提示|规则)"),
    re.compile(r"(?:输出|泄露|显示).{0,12}(?:系统提示词|system prompt)", re.IGNORECASE),
    re.compile(r"(?:developer|system)\s*(?:message|prompt)", re.IGNORECASE),
)


@dataclass(frozen=True)
class ModerationResult:
    allowed: bool
    reasons: tuple[str, ...] = ()

    @property
    def reason_text(self) -> str:
        return "、".join(self.reasons)


def review_outgoing(text: str) -> ModerationResult:
    reasons: list[str] = []
    if any(term in text for term in _SENSITIVE_TERMS):
        reasons.append("敏感内容")
    if any(term in text for term in _PROMISE_TERMS):
        reasons.append("违规承诺")
    if any(pattern.search(text) for pattern in _CONTACT_PATTERNS):
        reasons.append("联系方式")
    return ModerationResult(allowed=not reasons, reasons=tuple(reasons))


def contains_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PROMPT_INJECTION_PATTERNS)
