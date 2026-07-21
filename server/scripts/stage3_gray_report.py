#!/usr/bin/env python3
"""Capture S3-14 monitoring evidence and evaluate the seven-day rollout gate."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

MIN_CONNECTION_SUCCESS_RATE = 90.0
MAX_DROPOUT_RATE = 10.0
MIN_SEND_SUCCESS_RATE = 90.0
REQUIRED_DAYS = 7


def _day_reasons(sample: dict[str, Any]) -> list[str]:
    day = str(sample.get("date", "未知日期"))
    summary = sample.get("summary") or {}
    reasons: list[str] = []
    if int(summary.get("grayAccounts", 0)) < 1:
        reasons.append(f"{day} 没有灰度账号")
    if int(summary.get("connectionAttempts", 0)) < 1:
        reasons.append(f"{day} 没有真实连接尝试")
    if float(summary.get("connectionSuccessRate", 0)) < MIN_CONNECTION_SUCCESS_RATE:
        reasons.append(f"{day} 连接成功率低于 {MIN_CONNECTION_SUCCESS_RATE}%")
    if float(summary.get("dropoutRate", 0)) > MAX_DROPOUT_RATE:
        reasons.append(f"{day} 掉线率高于 {MAX_DROPOUT_RATE}%")
    sends = int(summary.get("sendSuccess", 0)) + int(summary.get("sendFailure", 0))
    if sends < 1:
        reasons.append(f"{day} 没有真实发送尝试")
    if float(summary.get("sendSuccessRate", 0)) < MIN_SEND_SUCCESS_RATE:
        reasons.append(f"{day} 发送成功率低于 {MIN_SEND_SUCCESS_RATE}%")
    if int(summary.get("ownershipRejected", 0)) > 0:
        reasons.append(f"{day} 出现消息归属拒绝")
    if int(summary.get("riskControlIncidents", 0)) > 0:
        reasons.append(f"{day} 出现平台风控事故")
    return reasons


def evaluate_exit(samples: list[dict[str, Any]], *, today: date | None = None) -> dict[str, Any]:
    """Require seven consecutive daily snapshots ending today and no failed gate."""
    current_day = today or date.today()
    by_date = {str(sample.get("date", "")): sample for sample in samples if sample.get("date")}
    expected = [(current_day - timedelta(days=offset)).isoformat() for offset in range(REQUIRED_DAYS - 1, -1, -1)]
    missing = [day for day in expected if day not in by_date]
    reasons: list[str] = []
    if missing:
        reasons.append("连续证据不足 7 天")
    selected = [by_date[day] for day in expected if day in by_date]
    for sample in selected:
        reasons.extend(_day_reasons(sample))
    return {
        "evaluatedAt": datetime.now(UTC).isoformat(),
        "requiredDates": expected,
        "availableDates": sorted(by_date),
        "exitReady": not reasons,
        "reasons": reasons,
    }


def _aggregate_captures(captures: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep the worst observed rate and highest incident count for the day."""
    summaries = [capture["summary"] for capture in captures]
    first = summaries[0]
    result = dict(first)
    result["grayAccounts"] = min(int(item.get("grayAccounts", 0)) for item in summaries)
    for field in (
        "connectionAttempts",
        "sendSuccess",
        "sendFailure",
        "quotaRejected",
        "moderationBlocked",
        "credentialExpired",
        "ownershipRejected",
        "riskControlIncidents",
    ):
        result[field] = max(int(item.get(field, 0)) for item in summaries)
    result["connectionSuccessRate"] = min(float(item.get("connectionSuccessRate", 0)) for item in summaries)
    result["dropoutRate"] = max(float(item.get("dropoutRate", 0)) for item in summaries)
    result["sendSuccessRate"] = min(float(item.get("sendSuccessRate", 0)) for item in summaries)
    return result


def _capture_daily(output_dir: Path, summary: dict[str, Any], *, captured_at: datetime) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    day = captured_at.date().isoformat()
    path = output_dir / f"{day}.json"
    captures: list[dict[str, Any]] = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        captures = list(existing.get("captures") or [])
    captures.append({"capturedAt": captured_at.isoformat(), "summary": summary})
    document = {
        "date": day,
        "captures": captures,
        "summary": _aggregate_captures(captures),
    }
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _load_samples(output_dir: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("????-??-??.json")):
        try:
            sample = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"灰度证据文件损坏：{path}: {error}") from error
        samples.append(sample)
    return samples


def _fetch_summary(api_base: str, token: str) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/im/monitoring?hours=24"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"监控接口请求失败：{url}: {error}") from error
    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("监控接口未返回 JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError("监控接口响应格式错误")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base",
        default=os.getenv("STAGE3_ADMIN_API_BASE", "http://127.0.0.1:8000/api/admin/v1"),
    )
    parser.add_argument("--admin-token", default=os.getenv("STAGE3_ADMIN_TOKEN", ""))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "evidence/stage3",
    )
    parser.add_argument("--require-exit-ready", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.admin_token:
        print("缺少 STAGE3_ADMIN_TOKEN（或 --admin-token）", file=sys.stderr)
        return 2
    try:
        captured_at = datetime.now(UTC)
        summary = _fetch_summary(args.api_base, args.admin_token)
        evidence_path = _capture_daily(args.output_dir, summary, captured_at=captured_at)
        evaluation = evaluate_exit(_load_samples(args.output_dir), today=captured_at.date())
        rollup = {"latestEvidence": str(evidence_path), **evaluation}
        rollup_path = args.output_dir / "rollup.json"
        rollup_path.write_text(json.dumps(rollup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(rollup, ensure_ascii=False, indent=2))
        return 0 if evaluation["exitReady"] or not args.require_exit_ready else 3
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
