"""Activation-code format contract."""

import re

from app.modules.activation.code_generator import generate_code, verify_code_format


def test_generated_code_uses_five_groups_and_is_immediately_verifiable() -> None:
    code = generate_code()

    assert re.fullmatch(r"ORAL(?:-[A-HJ-NP-Z2-9]{4}){5}", code)
    assert verify_code_format(code)
    assert verify_code_format(f"  {code.lower()}  ")


def test_legacy_four_group_display_shape_is_rejected() -> None:
    assert not verify_code_format("ORAL-ABCD-EFGH-JKLM-NPQR")
