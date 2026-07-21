"""
URL/ID 识别器：自动识别平台（抖音/小红书）并标准化为可解析的URL。
支持：分享短链、完整链接、视频ID、发现页链接等多种形式。
"""

import re
from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"
    UNKNOWN = "unknown"


@dataclass
class ResolvedInput:
    platform: Platform
    url: str  # 标准化后可直接传给解析API的URL
    raw_input: str  # 用户原始输入
    is_id: bool = False  # 是否为纯ID输入


# ---- 抖音 ----
DOUYIN_PATTERNS: list[re.Pattern] = [
    re.compile(r"https?://v\.douyin\.com/[\w/]+"),  # 分享短链
    re.compile(r"https?://www\.douyin\.com/video/\d+"),  # 完整链接
    re.compile(r"https?://www\.iesdouyin\.com/share/video/[\w/]+"),  # 发现页
    re.compile(r"https?://www\.douyin\.com/note/\d+"),  # 图文笔记
    re.compile(r"https?://www\.douyin\.com/discover\?.*modal_id=\d+"),  # 发现页带参数
]
DOUYIN_ID_PATTERN = re.compile(r"^\d{17,20}$")  # 纯视频ID（17-20位数字）

# ---- 小红书 ----
XHS_PATTERNS: list[re.Pattern] = [
    re.compile(r"https?://xhslink\.com/[\w/]+"),  # 分享短链
    re.compile(r"https?://www\.xiaohongshu\.com/explore/[\w]+"),  # 探索页
    re.compile(r"https?://www\.xiaohongshu\.com/discovery/item/[\w]+"),  # 发现页
    re.compile(r"https?://www\.xiaohongshu\.com/a/[\w]+"),  # 短链变体
]
XHS_ID_PATTERN = re.compile(r"^[0-9a-f]{24}$")  # 笔记ID（24位hex）


def resolve_input(raw: str) -> ResolvedInput:
    """
    识别用户输入的平台类型，并标准化为可传给 Douyidou 的 URL。

    支持输入：
    - 抖音：短链 / 完整链接 / 视频ID(17-20位数字)
    - 小红书：短链 / 完整链接 / 笔记ID(24位hex)
    - 其他URL：透传（由 Douyidou 自行判断平台）
    """
    text = raw.strip()

    # 抖音：纯视频ID → 拼接完整链接
    if DOUYIN_ID_PATTERN.match(text):
        url = f"https://www.douyin.com/video/{text}"
        return ResolvedInput(platform=Platform.DOUYIN, url=url, raw_input=raw, is_id=True)

    # 小红书：纯笔记ID → 拼接完整链接
    if XHS_ID_PATTERN.match(text):
        url = f"https://www.xiaohongshu.com/explore/{text}"
        return ResolvedInput(platform=Platform.XIAOHONGSHU, url=url, raw_input=raw, is_id=True)

    # URL 形式：匹配平台
    for pat in DOUYIN_PATTERNS:
        if pat.search(text):
            return ResolvedInput(platform=Platform.DOUYIN, url=text, raw_input=raw)

    for pat in XHS_PATTERNS:
        if pat.search(text):
            return ResolvedInput(platform=Platform.XIAOHONGSHU, url=text, raw_input=raw)

    # 通用URL：透传给 Douyidou（其内部支持多平台）
    if text.startswith(("http://", "https://")):
        # 尝试从域名推断平台
        if "douyin" in text:
            return ResolvedInput(platform=Platform.DOUYIN, url=text, raw_input=raw)
        if "xiaohongshu" in text or "xhslink" in text:
            return ResolvedInput(platform=Platform.XIAOHONGSHU, url=text, raw_input=raw)
        return ResolvedInput(platform=Platform.UNKNOWN, url=text, raw_input=raw)

    # 无法识别的输入
    return ResolvedInput(platform=Platform.UNKNOWN, url=text, raw_input=raw)
