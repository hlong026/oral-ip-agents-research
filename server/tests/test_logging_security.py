"""Production log and audit redaction regressions."""

import logging
import sys

from app.core.logging import SensitiveDataFilter, _sanitize, sanitize_loguru_record, sanitize_text


def test_sensitive_values_are_redacted_from_free_form_text() -> None:
    raw = (
        "phone=13812345678 Authorization: Bearer access-secret "
        "https://media.example/video?X-Amz-Signature=signed-secret&token=query-secret "
        "Cookie=sessionid=cookie-secret"
    )

    sanitized = sanitize_text(raw)

    assert "13812345678" not in sanitized
    assert "access-secret" not in sanitized
    assert "signed-secret" not in sanitized
    assert "query-secret" not in sanitized
    assert "cookie-secret" not in sanitized
    assert "138****5678" in sanitized


def test_structured_error_text_is_redacted() -> None:
    event = {
        "event": "provider failed token=provider-secret",
        "error": "request failed?signature=url-secret",
        "phone": "13912345678",
        "token": "bare-provider-secret",
    }

    sanitized = _sanitize(None, "warning", event)

    assert sanitized["event"] == "provider failed token=***"
    assert sanitized["error"] == "request failed?signature=***"
    assert sanitized["phone"] == "139****5678"
    assert sanitized["token"] == "***"


def test_standard_library_log_records_are_redacted() -> None:
    record = logging.LogRecord(
        name="vendor",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="cookie=session-secret phone=13712345678",
        args=(),
        exc_info=None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert record.getMessage() == "cookie=*** phone=137****5678"


def test_standard_library_exception_traceback_is_redacted() -> None:
    try:
        raise RuntimeError("token=exception-secret phone=13612345678")
    except RuntimeError:
        record = logging.LogRecord(
            name="vendor",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="provider failed cookie=session-secret",
            args=(),
            exc_info=sys.exc_info(),
        )

    assert SensitiveDataFilter().filter(record) is True
    rendered = logging.Formatter("%(message)s").format(record)
    assert "exception-secret" not in rendered
    assert "session-secret" not in rendered
    assert "13612345678" not in rendered
    assert "136****5678" in rendered
    assert "RuntimeError" in rendered


def test_loguru_vendor_records_drop_tracebacks_and_redact_messages() -> None:
    record = {
        "message": "Cookie=session-secret token=provider-secret phone=13512345678",
        "exception": object(),
    }

    assert sanitize_loguru_record(record) is True
    assert record["message"] == "Cookie=*** token=*** phone=135****5678"
    assert record["exception"] is None
