"""Activation-code format contract."""

import re

from app.modules.activation.code_generator import generate_code, verify_code_format


def test_generated_code_uses_windows_style_five_by_five() -> None:
    code = generate_code()

    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{5}(?:-[A-HJ-NP-Z2-9]{5}){4}", code)
    assert verify_code_format(code)
    assert verify_code_format(f"  {code.lower()}  ")


def test_legacy_oral_prefixed_code_still_verifiable() -> None:
    # 存量已发放的 ORAL 旧码必须保持可登录（校验位算法为旧 4 位规则）
    from app.modules.activation.code_generator import _ALPHABET, _checksum

    payload = _ALPHABET[:16]  # 确定性 16 字符载荷
    legacy = f"ORAL-{payload[0:4]}-{payload[4:8]}-{payload[8:12]}-{payload[12:16]}-{_checksum(payload, 4)}"
    assert verify_code_format(legacy)


def test_tampered_or_malformed_codes_are_rejected() -> None:
    code = generate_code()
    # 篡改校验位
    flat = code.replace("-", "")
    tampered = flat[:24] + ("A" if flat[24] != "A" else "B")
    assert not verify_code_format("-".join(tampered[i : i + 5] for i in range(0, 25, 5)))
    # 旧展示形制（4 段）与错误前缀
    assert not verify_code_format("ORAL-ABCD-EFGH-JKLM-NPQR")
    assert not verify_code_format("XXXX-XXXX-XXXX-XXXX-XXXX")
