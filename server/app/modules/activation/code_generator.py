"""激活码生成算法（HMAC-SHA256 签名，防伪造）

格式：XXXXX-XXXXX-XXXXX-XXXXX-XXXXX（Windows 产品密钥风格，25 位有效字符）
- 20 字符 base32 随机载荷
- 5 字符 HMAC 校验位
兼容：存量 ORAL-XXXX-XXXX-XXXX-XXXX-XXXX 旧码仍可通过校验登录
"""

import hashlib
import hmac
import secrets

from app.core.config import get_settings

_LEGACY_PREFIX = "ORAL"
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 字符，去除易混淆 0/O/1/I


def _get_secret() -> bytes:
    """获取激活码签名密钥（独立于 APP_SECRET）"""
    settings = get_settings()
    secret = getattr(settings, "activation_secret", "") or settings.app_secret
    return secret.encode("utf-8")


def _checksum(payload: str, length: int = 5) -> str:
    """HMAC-SHA256 校验位（新格式 5 字符；旧格式传 4）"""
    mac = hmac.new(_get_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    # 取前 N 个 hex 字符映射到 _ALPHABET
    return "".join(_ALPHABET[int(c, 16) % 32] for c in mac[:length])


def generate_code() -> str:
    """生成单个激活码：XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"""
    # 20 字符随机载荷（100 bit 熵）
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    full = raw + _checksum(raw)  # 25 字符
    return "-".join(full[i : i + 5] for i in range(0, 25, 5))


def verify_code_format(code: str) -> bool:
    """校验激活码格式 + HMAC 签名（兼容新旧两种格式）"""
    # 去除空格、统一大写
    code = code.strip().upper().replace(" ", "")
    parts = code.split("-")
    # 新格式：XXXXX-XXXXX-XXXXX-XXXXX-XXXXX（5 段 × 5 位，无前缀）
    if len(parts) == 5 and all(len(p) == 5 for p in parts):
        flat = "".join(parts)
        payload, check = flat[:20], flat[20:]
        if not all(c in _ALPHABET for c in flat):
            return False
        return hmac.compare_digest(check, _checksum(payload))
    # 旧格式：ORAL-XXXX-XXXX-XXXX-XXXX-XXXX（存量已发放码兼容，不再新发）
    if len(parts) == 6 and parts[0] == _LEGACY_PREFIX and all(len(p) == 4 for p in parts[1:]):
        payload = "".join(parts[1:5])  # 16 字符
        check = parts[5]  # 4 字符校验位
        if not all(c in _ALPHABET for c in payload + check):
            return False
        return hmac.compare_digest(check, _checksum(payload, 4))
    return False


def generate_batch(count: int) -> list[str]:
    """批量生成激活码（去重）"""
    codes: set[str] = set()
    while len(codes) < count:
        codes.add(generate_code())
    return list(codes)


def hash_code(code: str) -> str:
    """以服务端 pepper 对规范化激活码做不可逆索引，避免数据库泄露明文码。"""
    normalized = code.strip().upper().replace(" ", "")
    return hmac.new(_get_secret(), normalized.encode("utf-8"), hashlib.sha256).hexdigest()
