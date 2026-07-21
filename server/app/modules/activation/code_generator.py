"""激活码生成算法（HMAC-SHA256 签名，防伪造）

格式：ORAL-XXXX-XXXX-XXXX-XXXX（20 位有效字符）
- 16 字符 base32 随机载荷
- 4 字符 HMAC 校验位（取前 4 位）
"""

import hashlib
import hmac
import secrets

from app.core.config import get_settings

_PREFIX = "ORAL"
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 字符，去除易混淆 0/O/1/I


def _get_secret() -> bytes:
    """获取激活码签名密钥（独立于 APP_SECRET）"""
    settings = get_settings()
    secret = getattr(settings, "activation_secret", "") or settings.app_secret
    return secret.encode("utf-8")


def _checksum(payload: str) -> str:
    """HMAC-SHA256 校验位（4 字符）"""
    mac = hmac.new(_get_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    # 取前 4 个 hex 字符映射到 _ALPHABET
    return "".join(_ALPHABET[int(c, 16) % 32] for c in mac[:4])


def generate_code() -> str:
    """生成单个激活码：ORAL-XXXX-XXXX-XXXX-XXXX"""
    # 16 字符随机载荷
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    check = _checksum(raw)
    full = raw + check  # 20 字符
    return f"{_PREFIX}-{full[0:4]}-{full[4:8]}-{full[8:12]}-{full[12:16]}-{full[16:20]}"


def verify_code_format(code: str) -> bool:
    """校验激活码格式 + HMAC 签名"""
    # 去除空格、统一大写
    code = code.strip().upper().replace(" ", "")
    # 格式：ORAL-XXXX-XXXX-XXXX-XXXX
    parts = code.split("-")
    if len(parts) != 6 or parts[0] != _PREFIX:
        return False
    if not all(len(p) == 4 for p in parts[1:]):
        return False
    # 提取 20 字符
    payload = "".join(parts[1:5])  # 16 字符
    check = parts[5]  # 4 字符校验位
    # 验证字符集
    if not all(c in _ALPHABET for c in payload + check):
        return False
    # HMAC 校验
    expected = _checksum(payload)
    return hmac.compare_digest(check, expected)


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
