"""S3-14 seven-day gray evidence gate."""

from argparse import Namespace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts import stage3_gray_report as report
from scripts.stage3_gray_report import _aggregate_captures, evaluate_exit


def _clean_day(day: date) -> dict:
    return {
        "date": day.isoformat(),
        "summary": {
            "grayAccounts": 1,
            "connectionAttempts": 10,
            "connectionSuccessRate": 100.0,
            "dropoutRate": 0.0,
            "sendSuccess": 20,
            "sendFailure": 0,
            "sendSuccessRate": 100.0,
            "ownershipRejected": 0,
            "riskControlIncidents": 0,
        },
    }


def test_exit_requires_seven_consecutive_days_with_real_activity() -> None:
    today = date(2026, 7, 21)
    six_days = [_clean_day(today - timedelta(days=offset)) for offset in range(5, -1, -1)]

    result = evaluate_exit(six_days, today=today)

    assert result["exitReady"] is False
    assert "连续证据不足 7 天" in result["reasons"]


def test_exit_rejects_any_ownership_or_risk_control_incident() -> None:
    today = date(2026, 7, 21)
    seven_days = [_clean_day(today - timedelta(days=offset)) for offset in range(6, -1, -1)]
    seven_days[2]["summary"]["ownershipRejected"] = 1
    seven_days[4]["summary"]["riskControlIncidents"] = 1

    result = evaluate_exit(seven_days, today=today)

    assert result["exitReady"] is False
    assert any("归属拒绝" in reason for reason in result["reasons"])
    assert any("风控事故" in reason for reason in result["reasons"])


def test_exit_accepts_seven_clean_consecutive_days() -> None:
    today = date(2026, 7, 21)
    seven_days = [_clean_day(today - timedelta(days=offset)) for offset in range(6, -1, -1)]

    result = evaluate_exit(seven_days, today=today)

    assert result["exitReady"] is True
    assert result["reasons"] == []


def test_exit_rejects_seven_files_with_a_missing_calendar_day() -> None:
    today = date(2026, 7, 21)
    samples = [_clean_day(today - timedelta(days=offset)) for offset in (7, 5, 4, 3, 2, 1, 0)]

    result = evaluate_exit(samples, today=today)

    assert result["exitReady"] is False
    assert "连续证据不足 7 天" in result["reasons"]


def test_daily_rollup_keeps_worst_rates_and_highest_incident_count() -> None:
    summary = _clean_day(date(2026, 7, 21))["summary"]
    degraded = {**summary, "connectionSuccessRate": 91.0, "dropoutRate": 9.0, "riskControlIncidents": 1}

    result = _aggregate_captures([{"summary": summary}, {"summary": degraded}])

    assert result["connectionSuccessRate"] == 91.0
    assert result["dropoutRate"] == 9.0
    assert result["riskControlIncidents"] == 1


def test_cli_gate_writes_evidence_but_returns_three_before_seven_days(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "temporary-admin-token"
    monkeypatch.setattr(
        report,
        "parse_args",
        lambda: Namespace(
            api_base="http://example.test/api/admin/v1",
            admin_token=token,
            output_dir=tmp_path,
            require_exit_ready=True,
        ),
    )
    monkeypatch.setattr(report, "_fetch_summary", lambda *_args: _clean_day(date.today())["summary"])

    exit_code = report.main()

    assert exit_code == 3
    assert (tmp_path / "rollup.json").is_file()
    assert token not in "".join(path.read_text(encoding="utf-8") for path in tmp_path.glob("*.json"))


def test_cli_returns_two_for_corrupt_daily_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = datetime.now(UTC).date().isoformat()
    (tmp_path / f"{day}.json").write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(
        report,
        "parse_args",
        lambda: Namespace(
            api_base="http://example.test/api/admin/v1",
            admin_token="temporary-admin-token",
            output_dir=tmp_path,
            require_exit_ready=True,
        ),
    )
    monkeypatch.setattr(report, "_fetch_summary", lambda *_args: _clean_day(date.today())["summary"])

    assert report.main() == 2
