"""Build a fail-closed Production Go/No-Go report from Staging evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MANUAL_STATUSES = {"manual_pending", "manual_pass", "manual_fail"}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _automated_evidence(source: str, evidence_dir: Path, git_commit: str) -> tuple[bool, list[str], str | None]:
    if source == "deploy":
        path = evidence_dir / f"deploy-{git_commit}.json"
        if not path.is_file():
            return False, [], "missing deployment evidence"
        payload = _read_json(path)
        ok = payload.get("ok") is True and payload.get("gitCommit") == git_commit
        return ok, [str(path)], None if ok else "deployment evidence does not match release commit"

    if source == "smoke":
        path = evidence_dir / f"smoke-{git_commit}.json"
        if not path.is_file():
            return False, [], "missing smoke evidence"
        payload = _read_json(path)
        ok = payload.get("ok") is True and payload.get("gitCommit") == git_commit
        return ok, [str(path)], None if ok else "smoke evidence does not match release commit"

    if source == "backup":
        backup_dir = evidence_dir / "backups"
        candidates = sorted(backup_dir.glob(f"db-{git_commit[:12]}-*.json"))
        if not candidates:
            return False, [], "missing database backup metadata"
        metadata_path = candidates[-1]
        metadata = _read_json(metadata_path)
        dump_name = metadata.get("dumpFile")
        if not isinstance(dump_name, str) or not dump_name or "/" in dump_name or "\\" in dump_name:
            return False, [str(metadata_path)], "invalid dump filename in backup metadata"
        dump_path = backup_dir / dump_name
        if not dump_path.is_file():
            return False, [str(metadata_path)], "backup dump file is missing"
        expected_sha = metadata.get("sha256")
        ok = (
            metadata.get("kind") == "postgresql-backup"
            and metadata.get("ok") is True
            and metadata.get("gitCommit") == git_commit
            and isinstance(expected_sha, str)
            and _sha256(dump_path) == expected_sha
        )
        refs = [str(metadata_path), str(dump_path)]
        return ok, refs, None if ok else "database backup metadata or SHA-256 is invalid"

    return False, [], f"unknown automated evidence source: {source}"


def build_report(
    *,
    cases_path: Path,
    evidence_dir: Path,
    manual_results_path: Path,
    git_commit: str,
) -> dict[str, Any]:
    if not _GIT_SHA_RE.fullmatch(git_commit):
        raise ValueError("git commit must be a 40-character lowercase SHA")
    cases_doc = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
    manual_doc = _read_json(manual_results_path)
    if not isinstance(cases_doc, dict) or not isinstance(cases_doc.get("cases"), list):
        raise ValueError("acceptance cases document is invalid")
    manual_results = manual_doc.get("results")
    if not isinstance(manual_results, dict):
        raise ValueError("manual results document is invalid")

    results: list[dict[str, Any]] = []
    overall_ok = True
    seen_ids: set[str] = set()

    for raw_case in cases_doc["cases"]:
        if not isinstance(raw_case, dict):
            raise ValueError("acceptance case must be an object")
        case_id = str(raw_case.get("id") or "").strip()
        if not case_id or case_id in seen_ids:
            raise ValueError(f"invalid or duplicate acceptance case id: {case_id!r}")
        seen_ids.add(case_id)
        mode = raw_case.get("mode")
        required = raw_case.get("required") is True
        gate = str(raw_case.get("gate") or "")
        description = str(raw_case.get("description") or "")

        if mode == "automated":
            source = str(raw_case.get("source") or "")
            ok, evidence, reason = _automated_evidence(source, evidence_dir, git_commit)
            status = "pass" if ok else "fail"
        elif mode == "manual":
            entry = manual_results.get(case_id)
            if not isinstance(entry, dict):
                status = "manual_pending"
                evidence = []
                reason = "manual result is missing"
                ok = False
            else:
                status = str(entry.get("status") or "manual_pending")
                if status not in _MANUAL_STATUSES:
                    raise ValueError(f"invalid manual status for {case_id}: {status}")
                evidence_raw = entry.get("evidence")
                evidence = [str(item) for item in evidence_raw] if isinstance(evidence_raw, list) else []
                ok = status == "manual_pass" and bool(evidence)
                reason = None if ok else "manual case has not passed with evidence"
        else:
            raise ValueError(f"invalid mode for {case_id}: {mode}")

        if required and not ok:
            overall_ok = False
        results.append(
            {
                "id": case_id,
                "gate": gate,
                "mode": mode,
                "required": required,
                "status": status,
                "ok": ok,
                "description": description,
                "evidence": evidence,
                "reason": reason,
            }
        )

    unknown_manual_ids = sorted(set(manual_results) - {item["id"] for item in results if item["mode"] == "manual"})
    if unknown_manual_ids:
        raise ValueError(f"manual results contain unknown case ids: {unknown_manual_ids}")

    return {
        "schemaVersion": 1,
        "kind": "production-acceptance",
        "gitCommit": git_commit,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision": "GO" if overall_ok else "NO_GO",
        "ok": overall_ok,
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a fail-closed Production Go/No-Go acceptance report")
    parser.add_argument("--cases", default="/app/acceptance/acceptance-cases.yaml")
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--manual-results", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_path = Path(args.output)
    report = build_report(
        cases_path=Path(args.cases),
        evidence_dir=Path(args.evidence_dir),
        manual_results_path=Path(args.manual_results),
        git_commit=args.git_commit,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_path.chmod(0o600)
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "output": str(output_path)}, sort_keys=True))
    raise SystemExit(0 if report["ok"] else 3)


if __name__ == "__main__":
    main()
