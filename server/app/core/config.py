"""全局配置（pydantic-settings，.env 驱动）"""

from functools import lru_cache
import re
from ipaddress import ip_address
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 基础
    app_env: str = "dev"
    app_secret: str = "dev-secret-change-me"
    config_encryption_key: str = ""  # Provider 密钥专用；生产环境必须与 JWT APP_SECRET 分离
    publish_session_encryption_key: str = ""  # 发布 Cookie 专用 Fernet 密钥
    bootstrap_admin_phone: str = ""
    bootstrap_admin_password: str = ""
    api_prefix: str = "/api/v1"
    cors_origins: str = ""

    # 数据层
    database_url: str = "sqlite+aiosqlite:///./oral.db"
    redis_url: str = "redis://localhost:6379/0"
    task_queue_name: str = "oral"
    redis_operation_timeout_seconds: float = 3.0

    # 存储
    storage_driver: str = "local"  # local | s3
    local_storage_dir: str = "./storage"
    media_public_base_url: str = ""  # 真实云端 ASR 回源地址，例如 https://api.example.com
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "oral"
    s3_secret_key: str = "oral_dev_minio"
    s3_bucket: str = "oral-media"
    s3_region: str = "us-east-1"
    s3_addressing_style: str = "virtual"
    s3_signature_version: str = "s3"
    s3_max_pool_connections: int = 32
    s3_connect_timeout_seconds: float = 5.0
    s3_read_timeout_seconds: float = 60.0
    s3_max_attempts: int = 4
    s3_multipart_threshold_mb: int = 64
    s3_multipart_chunksize_mb: int = 16

    # JWT（F-601 / C7）
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 120
    refresh_token_ttl_days: int = 30
    single_session_kick: bool = False

    # 激活码
    activation_secret: str = ""  # 激活码 HMAC 签名密钥（空则回退 app_secret）
    activation_failure_limit: int = 10  # 10 分钟窗口内失败满 10 次即锁定
    activation_rate_window_seconds: int = 600  # 10 分钟滑动窗口
    activation_lock_seconds: int = 900  # 锁定 15 分钟

    # LLM
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    doubao_api_key: str = ""
    yunwu_api_key: str = ""
    yunwu_base_url: str = ""

    # MiniMax 声音
    minimax_api_key: str = ""
    minimax_group_id: str = ""

    # 飞影数字人（内部代号，用户侧白标不暴露）
    feiying_api_key: str = ""
    feiying_base_url: str = "https://hfw-api.hifly.cc"
    feiying_poll_interval: float = 5.0  # 轮询间隔（秒）
    feiying_poll_max_attempts: int = 60  # 最大轮询次数（5分钟超时）
    feiying_webhook_secret: str = ""  # 回调验签（预留）
    webhook_retry_max_attempts: int = 3
    webhook_retry_base_seconds: int = 30

    # 第三方解析兜底
    parse_api_url: str = ""
    parse_api_key: str = ""

    # Douyidou 视频解析（抖音/小红书去水印 + 文案提取）
    douyidou_app_id: str = ""
    douyidou_app_secret: str = ""
    douyidou_base_url: str = "https://gateway.diadi.cn"

    # 阿里云 Fun-ASR 语音转写（DashScope）
    dashscope_api_key: str = ""
    dashscope_workspace_id: str = ""  # 选填，企业专属业务空间；普通用户留空即可
    dashscope_region: str = "cn-beijing"  # cn-beijing | ap-southeast-1
    asr_model: str = "fun-asr"  # fun-asr(异步,≤12h) | fun-asr-flash(同步,≤5min)
    asr_flash_model: str = "fun-asr-flash-2026-06-15"  # 短音频同步模型
    asr_flash_threshold_sec: int = 300  # ≤该秒数走Flash同步，>则走异步
    asr_poll_interval: float = 2.0  # 异步轮询间隔(秒)
    asr_poll_max_attempts: int = 90  # 最大轮询次数（3分钟超时）

    # 流水线并发闸门（F-406）
    pipeline_max_concurrency: int = 5
    # Mock 降级开关：未显式配置时按环境推导（仅 dev/test 默认开）；非 dev/test 环境强制关闭
    provider_mock_fallback_enabled: bool | None = None

    @property
    def mock_fallback_allowed(self) -> bool:
        """Mock 降级是否允许：生产等非 dev/test 环境无条件 False，不受 .env 误配影响。"""
        if self.app_env not in {"dev", "test"}:
            return False
        if self.provider_mock_fallback_enabled is None:
            return True
        return self.provider_mock_fallback_enabled

    # 发布模块（social-auto-upload 浏览器自动化）
    # 默认无头：扫码登录二维码经 API 传给前端展示，不再弹出浏览器窗口
    # （有头窗口易被用户扫完码后顺手关闭，导致后端轮询页面失效、登录判失败）
    publish_browser_headless: bool = True
    publish_browser_executable_path: str = ""  # 留空时自动探测本机 Chrome / Edge
    publish_max_concurrency: int = 2  # 浏览器并发槽位数
    publish_cookie_heartbeat_min: int = 30  # Cookie 心跳检测间隔（分钟）
    # 仅列出已经用真实账号验收通过的平台；未列出平台只提供完整人工发布包。
    publish_verified_platforms: str = ""
    # 本机验证开关：dev 环境下也强制使用真实发布驱动（真实扫码绑定/发布），
    # 而不改动 app_env——避免切到 test 触发 StubBroker 导致后台队列静默失效。
    # 注意：仅开此开关不够，还需把目标平台加入 publish_verified_platforms，
    # 否则扫码入口会因 AUTOMATION_NOT_VERIFIED 返回 409。
    publish_force_real: bool = False

    # 抖音 IM 私信（启用后必须配置真实 APP_KEY；禁止 Mock 结果进入发送状态）
    im_enabled: bool = False
    douyin_im_app_key: str = ""
    douyin_im_aid: str = "6383"
    douyin_im_fpid: str = "9"
    douyin_im_access_key_suffix: str = "f8a69f1719916z"
    im_listen_only: bool = True  # 只读模式：允许生产启用，但禁止任何对外发送行为
    im_history_retention_days: int = 90
    im_metric_retention_days: int = 14
    im_cleanup_interval_hours: int = 24
    im_gray_enforced: bool = True
    im_gray_max_accounts: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_runtime_security(settings: Settings) -> None:
    # No-Go 解除：if im_listen_only=True，允许生产环境启用 IM（只读监听不发送）
    if settings.im_enabled and not settings.im_listen_only and settings.app_env not in {"dev", "test"}:
        raise RuntimeError("第三阶段合规结论为 No-Go：生产环境不得启用 IM_ENABLED(非只读模式)")
    if settings.im_enabled and not settings.douyin_im_app_key:
        raise RuntimeError("启用私信模块必须配置真实 DOUYIN_IM_APP_KEY，禁止使用 Mock 发送")
    if settings.app_env in {"dev", "test"}:
        return

    def is_placeholder(value: str) -> bool:
        normalized = value.strip().lower()
        return not normalized or any(
            marker in normalized for marker in ("replace_", "replace-", "change-me", "example.com", "dev-secret")
        )

    def has_url_host(value: str, schemes: set[str]) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in schemes and bool(parsed.hostname)

    def is_public_dns_hostname(hostname: str | None) -> bool:
        normalized = (hostname or "").strip().lower().rstrip(".")
        if not normalized or "." not in normalized:
            return False
        try:
            ip_address(normalized)
        except ValueError:
            pass
        else:
            return False
        return not normalized.endswith((".example", ".internal", ".invalid", ".lan", ".local", ".localhost", ".test"))

    allowed_tauri_origins = {"tauri://localhost", "https://tauri.localhost"}

    def is_allowed_cors_origin(origin: str) -> bool:
        if origin in allowed_tauri_origins:
            return True
        parsed = urlparse(origin)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and is_public_dns_hostname(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and parsed.path in {"", "/"}
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and not is_placeholder(origin)
        )

    errors: list[str] = []
    secrets = {
        "APP_SECRET": settings.app_secret,
        "CONFIG_ENCRYPTION_KEY": settings.config_encryption_key,
        "ACTIVATION_SECRET": settings.activation_secret,
        "PUBLISH_SESSION_ENCRYPTION_KEY": settings.publish_session_encryption_key,
        "FEIYING_WEBHOOK_SECRET": settings.feiying_webhook_secret,
    }
    for name, value in secrets.items():
        if is_placeholder(value) or len(value.encode("utf-8")) < 32:
            errors.append(f"{name} 必须是至少 32 字节的非占位随机值")
    if len(set(secrets.values())) != len(secrets):
        errors.append("应用安全密钥必须互不相同")

    if not has_url_host(settings.database_url, {"postgresql+asyncpg"}) or is_placeholder(settings.database_url):
        errors.append("DATABASE_URL 必须使用非占位的 PostgreSQL asyncpg 连接")
    if not has_url_host(settings.redis_url, {"redis", "rediss"}) or is_placeholder(settings.redis_url):
        errors.append("REDIS_URL 必须使用有效的 Redis 连接")

    cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if not cors_origins or any(not is_allowed_cors_origin(origin) for origin in cors_origins):
        errors.append("CORS_ORIGINS 必须只包含正式 HTTPS 域名或受控 Tauri Origin")

    if settings.storage_driver != "s3":
        errors.append("STORAGE_DRIVER 生产环境必须使用 s3")
    s3_url = urlparse(settings.s3_endpoint)
    if not has_url_host(settings.s3_endpoint, {"https"}) or is_placeholder(settings.s3_endpoint):
        errors.append("S3_ENDPOINT 生产环境必须是有效的 HTTPS 非占位地址")
    elif not is_public_dns_hostname(s3_url.hostname):
        errors.append("S3_ENDPOINT 生产环境不得使用 localhost、IP 或内网保留域名")
    if not re.fullmatch(r"[a-z]{2,3}-[a-z0-9-]+", settings.s3_region.strip()):
        errors.append("S3_REGION 必须是有效地域，例如 ap-guangzhou")
    if settings.s3_addressing_style != "virtual":
        errors.append("S3_ADDRESSING_STYLE 生产环境必须为 virtual")
    if settings.s3_signature_version not in {"s3", "s3v4"}:
        errors.append("S3_SIGNATURE_VERSION 仅支持 s3 或 s3v4")
    if settings.s3_max_pool_connections < 1:
        errors.append("S3_MAX_POOL_CONNECTIONS 必须大于 0")
    if settings.s3_connect_timeout_seconds <= 0 or settings.s3_read_timeout_seconds <= 0:
        errors.append("S3 连接与读取超时必须大于 0")
    if settings.s3_max_attempts < 1:
        errors.append("S3_MAX_ATTEMPTS 必须大于 0")
    if settings.s3_multipart_threshold_mb < 5 or settings.s3_multipart_chunksize_mb < 5:
        errors.append("S3 Multipart 阈值和分片大小不得小于 5MB")
    if s3_url.hostname and s3_url.hostname.endswith(".myqcloud.com"):
        expected_host = f"cos.{settings.s3_region}.myqcloud.com"
        if s3_url.hostname != expected_host:
            errors.append("腾讯云 COS Endpoint 必须与 S3_REGION 一致")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,49}-\d{5,}", settings.s3_bucket):
            errors.append("腾讯云 COS 的 S3_BUCKET 必须使用 BucketName-APPID 完整名称")
    if is_placeholder(settings.s3_access_key):
        errors.append("S3_ACCESS_KEY 必须是非占位值")
    if is_placeholder(settings.s3_secret_key) or len(settings.s3_secret_key.encode("utf-8")) < 32:
        errors.append("S3_SECRET_KEY 必须是至少 32 字节的非占位值")
    if is_placeholder(settings.s3_bucket):
        errors.append("S3_BUCKET 必须是非占位值")

    media_url = urlparse(settings.media_public_base_url)
    if (
        not has_url_host(settings.media_public_base_url, {"https"})
        or not is_public_dns_hostname(media_url.hostname)
        or media_url.username
        or media_url.password
        or media_url.params
        or media_url.query
        or media_url.fragment
        or is_placeholder(settings.media_public_base_url)
    ):
        errors.append("MEDIA_PUBLIC_BASE_URL 必须是公网可达的正式 HTTPS 地址")
    if not settings.publish_browser_headless:
        errors.append("PUBLISH_BROWSER_HEADLESS 生产环境必须为 true")

    if errors:
        raise RuntimeError("生产环境安全配置无效：" + "；".join(errors))
