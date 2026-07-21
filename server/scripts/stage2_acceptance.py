#!/usr/bin/env python3
"""第二阶段真实链路验收：固定链接 + 固定正文，各连续运行三次并留存证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TERMINAL_TASK = {"done", "failed", "canceled"}
TERMINAL_JOB = {"success", "failed", "export_ready"}
PIPELINE_MODULES = {"script_generation", "tts", "digital_human", "hd_export"}
SECRET_KEYS = {"accessToken", "refreshToken", "session", "cookie", "authorization"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "<redacted>" if key in SECRET_KEYS else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class ApiClient:
    def __init__(self, api_base: str, token: str, evidence_dir: Path) -> None:
        self.api_base = api_base.rstrip("/")
        self.origin = urllib.parse.urlsplit(self.api_base)
        self.token = token
        self.evidence_dir = evidence_dir
        self.exchange_index = 0

    def request(self, method: str, path: str, body: dict | None = None) -> Any:
        self.exchange_index += 1
        url = f"{self.api_base}{path}"
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        started = time.perf_counter()
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        status = 0
        response_body: Any = None
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                status = response.status
                raw = response.read()
            response_body = json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
            try:
                response_body = json.loads(raw)
            except json.JSONDecodeError:
                response_body = raw.decode(errors="replace")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        exchange = {
            "method": method,
            "path": path,
            "status": status,
            "elapsedMs": elapsed_ms,
            "request": redact(body),
            "response": redact(response_body),
        }
        exchange_path = self.evidence_dir / "http" / f"{self.exchange_index:04d}.json"
        exchange_path.parent.mkdir(parents=True, exist_ok=True)
        exchange_path.write_text(json.dumps(exchange, ensure_ascii=False, indent=2), encoding="utf-8")
        if not 200 <= status < 300:
            raise RuntimeError(f"{method} {path} -> HTTP {status}: {response_body}")
        return response_body

    def download(self, media_path: str, destination: Path) -> None:
        url = urllib.parse.urlunsplit((self.origin.scheme, self.origin.netloc, media_path, "", ""))
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"下载失败 {media_path}: {exc}") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=os.getenv("STAGE2_API_BASE", "http://127.0.0.1:8000/api/v1"))
    parser.add_argument("--ip-id", default=os.getenv("STAGE2_IP_ID", ""), required=False)
    parser.add_argument("--voice-id", default=os.getenv("STAGE2_VOICE_ID", ""), required=False)
    parser.add_argument("--avatar-id", default=os.getenv("STAGE2_AVATAR_ID", ""), required=False)
    parser.add_argument("--real-link", default=os.getenv("STAGE2_REAL_LINK", ""), required=False)
    parser.add_argument(
        "--body-file",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "e2e/fixtures/stage2-body.txt",
    )
    parser.add_argument("--platform", default=os.getenv("STAGE2_PLATFORM", "douyin"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=2700)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def require_inputs(args: argparse.Namespace) -> str:
    token = os.getenv("STAGE2_ACCESS_TOKEN", "")
    missing = [
        name
        for name, value in (
            ("STAGE2_ACCESS_TOKEN", token),
            ("STAGE2_IP_ID", args.ip_id),
            ("STAGE2_VOICE_ID", args.voice_id),
            ("STAGE2_AVATAR_ID", args.avatar_id),
            ("STAGE2_REAL_LINK", args.real_link),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("缺少真实验收参数：" + ", ".join(missing))
    if args.runs < 3:
        raise RuntimeError("第二阶段要求至少连续运行 3 次，--runs 不得小于 3")
    if not args.body_file.is_file():
        raise RuntimeError(f"固定正文不存在：{args.body_file}")
    return token


def quantity_for(unit: str, duration_seconds: int, text_length: int) -> int:
    if unit in {"per_minute", "per_second"}:
        return duration_seconds
    if unit == "per_1k_chars":
        return text_length
    if unit == "per_1k_tokens":
        return max(1, (text_length + 1) // 2)
    return 1


def quote_task(
    api: ApiClient,
    catalog: dict,
    *,
    has_link: bool,
    body: str,
    target_duration: int,
) -> dict:
    duration = max(target_duration, int(len(body) * 0.28 + 0.999999))
    text_length = max(len(body), int(duration / 0.28 + 0.999999))
    required = set(PIPELINE_MODULES)
    if has_link and not body:
        required.add("asr")
    items = [
        {
            "module": price["module"],
            "quantity": quantity_for(price["billingUnit"], duration, text_length),
        }
        for price in catalog["items"]
        if price["module"] in required
    ]
    if {item["module"] for item in items} != required:
        actual = sorted(item["module"] for item in items)
        raise RuntimeError(f"价格配置不完整：required={sorted(required)}, actual={actual}")
    return api.request("POST", "/billing/price-preview", {"items": items})


def wait_for_task(api: ApiClient, task_id: str, poll_seconds: float, timeout_seconds: int) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task = api.request("GET", f"/pipelines/{task_id}")
        if task["status"] in TERMINAL_TASK:
            return task
        time.sleep(poll_seconds)
    raise RuntimeError(f"流水线超时：{task_id}")


def wait_for_jobs(
    api: ApiClient,
    task_id: str,
    poll_seconds: float,
    timeout_seconds: int,
) -> list[dict]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        page = api.request("GET", "/publish/jobs?page=1&pageSize=100")
        jobs = [job for job in page["items"] if job["taskId"] == task_id]
        if jobs and all(job["status"] in TERMINAL_JOB for job in jobs):
            return jobs
        time.sleep(poll_seconds)
    raise RuntimeError(f"发布任务超时：{task_id}")


def probe_video(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"ffprobe 验证失败：{path}: {exc}") from exc
    return json.loads(result.stdout)


def validate_package(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "metadata.json" not in names or not any(name.startswith("video.") for name in names):
                raise RuntimeError(f"发布包缺少视频或 metadata.json：{names}")
            json.loads(archive.read("metadata.json"))
            return names
    except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise RuntimeError(f"发布包损坏：{path}") from exc


def run_case(
    api: ApiClient,
    args: argparse.Namespace,
    catalog: dict,
    body: str,
    target_duration: int,
    case_name: str,
    run_index: int,
) -> dict:
    source_url = args.real_link if case_name == "link" else ""
    script_text = body if case_name == "body" else ""
    quote = quote_task(
        api,
        catalog,
        has_link=bool(source_url),
        body=script_text,
        target_duration=target_duration,
    )
    task_payload = {
        "ipId": args.ip_id,
        "sourceUrl": source_url or None,
        "scriptText": script_text or None,
        "voiceId": args.voice_id,
        "avatarId": args.avatar_id,
        "mode": "auto",
        "platforms": [args.platform],
        "quoteId": quote["quoteId"],
    }
    started = time.perf_counter()
    task = api.request("POST", "/pipelines", task_payload)[0]
    task = wait_for_task(api, task["id"], args.poll_seconds, args.timeout_seconds)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if task["status"] != "done":
        raise RuntimeError(f"{case_name} 第 {run_index} 次失败：{task.get('error')}")
    artifacts = task.get("artifacts") or {}
    video_key = str(artifacts.get("final_video_key") or "")
    quality = artifacts.get("quality") or {}
    if not video_key or not isinstance(quality, dict) or not quality.get("passed"):
        raise RuntimeError(f"任务没有合格成片：task={task['id']}, quality={quality}")

    case_dir = api.evidence_dir / "runs" / f"{case_name}-{run_index}"
    video_path = case_dir / "final.mp4"
    api.download(f"/media/{video_key}", video_path)
    probe = probe_video(video_path)
    (case_dir / "ffprobe.json").write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")

    jobs = wait_for_jobs(api, task["id"], args.poll_seconds, args.timeout_seconds)
    packages = []
    for job in jobs:
        exported = api.request("POST", f"/publish/jobs/{job['id']}/export")
        package_path = case_dir / f"{job['platform']}-{job['id'][:8]}.zip"
        api.download(exported["packageUrl"], package_path)
        packages.append({"job": job, "path": str(package_path), "files": validate_package(package_path)})

    result = {
        "case": case_name,
        "run": run_index,
        "taskId": task["id"],
        "elapsedMs": elapsed_ms,
        "estimatedPoints": quote["estimatedPoints"],
        "settledPoints": task["quotaCost"],
        "steps": task["steps"],
        "quality": quality,
        "video": str(video_path),
        "ffprobe": probe,
        "packages": packages,
    }
    (case_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    args = parse_args()
    token = require_inputs(args)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or Path(__file__).resolve().parents[2] / "evidence" / "stage2" / timestamp
    output.mkdir(parents=True, exist_ok=False)
    api = ApiClient(args.api_base, token, output)
    body = args.body_file.read_text(encoding="utf-8").strip()
    if len(body) < 50:
        raise RuntimeError("固定正文至少需要 50 个字符")

    manifest = {
        "startedAt": datetime.now(UTC).isoformat(),
        "apiBase": args.api_base,
        "runs": args.runs,
        "platform": args.platform,
        "inputs": {
            "realLink": args.real_link,
            "realLinkSha256": hashlib.sha256(args.real_link.encode()).hexdigest(),
            "bodyFile": str(args.body_file),
            "bodySha256": hashlib.sha256(body.encode()).hexdigest(),
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    catalog = api.request("GET", "/catalog/module-prices")
    persona = api.request("GET", f"/personas/{args.ip_id}")
    capabilities = api.request("GET", "/publish/capabilities")
    selected_capability = next((item for item in capabilities if item["platform"] == args.platform), None)
    if selected_capability is None:
        raise RuntimeError(f"发布能力矩阵缺少平台：{args.platform}")
    before = {
        "quota": api.request("GET", "/billing/quota"),
        "usage": api.request("GET", "/billing/usage?page=1&pageSize=100"),
    }

    results = []
    for run_index in range(1, args.runs + 1):
        results.append(run_case(api, args, catalog, body, int(persona.get("videoDuration") or 60), "link", run_index))
        results.append(run_case(api, args, catalog, body, int(persona.get("videoDuration") or 60), "body", run_index))

    after = {
        "quota": api.request("GET", "/billing/quota"),
        "usage": api.request("GET", "/billing/usage?page=1&pageSize=100"),
    }
    publish_successes = [
        package["job"] for result in results for package in result["packages"] if package["job"]["status"] == "success"
    ]
    verified_publish = selected_capability["verificationStatus"] == "verified" and bool(publish_successes)
    blockers = [] if verified_publish else ["所选平台尚无本轮真实账号发布成功证据"]
    summary = {
        **manifest,
        "finishedAt": datetime.now(UTC).isoformat(),
        "capability": selected_capability,
        "results": results,
        "billingBefore": before,
        "billingAfter": after,
        "verifiedRealPublish": verified_publish,
        "blockers": blockers,
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"验收证据已保存：{output}")
    if blockers:
        print("真实成片链路通过，但发布验收未闭环：" + "；".join(blockers), file=sys.stderr)
        return 2
    print(f"第二阶段真实链路通过：{len(results)} 个成片任务，真实发布成功 {len(publish_successes)} 次")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"验收失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
