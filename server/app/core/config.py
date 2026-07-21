"""全局配置（pydantic-settings，.env 驱动）"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 基础
    app_env: str = "dev"
    app_secret: str = "dev-secret-change-me"
    config_encryption_key: str = ""  # Provider 密钥专用；生产环境必须与 JWT APP_SECRET 分离
    bootstrap_admin_phone: str = ""
    bootstrap_admin_password: str = ""
    api_prefix: str = "/api/v1"

    # 数据层
    database_url: str = "sqlite+aiosqlite:///./oral.db"
    redis_url: str = "redis://localhost:6379/0"

    # 存储
    storage_driver: str = "local"  # local | s3
    local_storage_dir: str = "./storage"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "oral"
    s3_secret_key: str = "oral_dev_minio"
    s3_bucket: str = "oral-media"

    # JWT（F-601 / C7）
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 120
    refresh_token_ttl_days: int = 30
    single_session_kick: bool = False

    # 激活码
    activation_secret: str = ""  # 激活码 HMAC 签名密钥（空则回退 app_secret）

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

    # 发布模块（social-auto-upload 浏览器自动化）
    # 默认无头：扫码登录二维码经 API 传给前端展示，不再弹出浏览器窗口
    # （有头窗口易被用户扫完码后顺手关闭，导致后端轮询页面失效、登录判失败）
    publish_browser_headless: bool = True
    publish_max_concurrency: int = 2  # 浏览器并发槽位数
    publish_cookie_heartbeat_min: int = 30  # Cookie 心跳检测间隔（分钟）

    # 抖音 IM 私信（#11: APP_KEY 移入配置，未配置时自动降级到 MockIMProvider）
    douyin_im_app_key: str = ""
    douyin_im_aid: str = "6383"
    douyin_im_fpid: str = "9"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_runtime_security(settings: Settings) -> None:
    if settings.app_env == "dev":
        return
    missing: list[str] = []
    if settings.app_secret == "dev-secret-change-me":
        missing.append("APP_SECRET")
    if not settings.config_encryption_key:
        missing.append("CONFIG_ENCRYPTION_KEY")
    if not settings.activation_secret:
        missing.append("ACTIVATION_SECRET")
    if missing:
        raise RuntimeError("生产环境缺少安全配置：" + ", ".join(missing))
