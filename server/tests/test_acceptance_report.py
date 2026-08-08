"""Production acceptance cannot turn green without complete, untampered evidence."""

import hashlib
import json
from pathlib import Path

from scripts.acceptance_report import build_report

ROOT = Path(__file__).resolve().parents[2]
GIT_COMMIT = "a" * 40


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _prepare_automated_evidence(tmp_path: Path) -> None:
    _write_json(tmp_path / f"deploy-{GIT_COMMIT}.json", {"ok": True, "gitCommit": GIT_COMMIT})
    _write_json(tmp_path / f"smoke-{GIT_COMMIT}.json", {"ok": True, "gitCommit": GIT_COMMIT})

    dump = tmp_path / "backups" / f"db-{GIT_COMMIT[:12]}-20260808T120000Z.dump"
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_bytes(b"verified-postgresql-dump")
    digest = hashlib.sha256(dump.read_bytes()).hexdigest()
    _write_json(
        dump.with_suffix(".json"),
        {
            "schemaVersion": 1,
            "kind": "postgresql-backup",
            "ok": True,
            "environment": "staging",
            "gitCommit": GIT_COMMIT,
            "dumpFile": dump.name,
            "sha256": digest,
        },
    )


def _manual_results(status: str, *, with_evidence: bool) -> dict[str, object]:
    cases = json.loads((ROOT / "deploy/acceptance/acceptance-cases.json").read_text(encoding="utf-8"))["cases"]
    return {
        "schemaVersion": 1,
        "results": {
            case["id"]: {
                "status": status,
                "evidence": [f"evidence://{case['id'].lower()}"] if with_evidence else [],
            }
            for case in cases
            if case["mode"] == "manual"
        },
    }


def _report(tmp_path: Path, manual: dict[str, object]) -> dict[str, object]:
    manual_path = tmp_path / "manual.json"
    _write_json(manual_path, manual)
    return build_report(
        cases_path=ROOT / "deploy/acceptance/acceptance-cases.json",
        evidence_dir=tmp_path,
        manual_results_path=manual_path,
        git_commit=GIT_COMMIT,
    )


def test_manual_pending_forces_no_go_even_with_all_automated_evidence(tmp_path: Path) -> None:
    _prepare_automated_evidence(tmp_path)
    report = _report(tmp_path, _manual_results("manual_pending", with_evidence=False))

    assert report["ok"] is False
    assert report["decision"] == "NO_GO"
    assert any(item["status"] == "manual_pending" for item in report["results"])


def test_manual_pass_without_evidence_still_forces_no_go(tmp_path: Path) -> None:
    _prepare_automated_evidence(tmp_path)
    report = _report(tmp_path, _manual_results("manual_pass", with_evidence=False))

    assert report["ok"] is False
    assert report["decision"] == "NO_GO"


def test_tampered_database_backup_forces_no_go(tmp_path: Path) -> None:
    _prepare_automated_evidence(tmp_path)
    dump = next((tmp_path / "backups").glob("*.dump"))
    dump.write_bytes(b"tampered")
    report = _report(tmp_path, _manual_results("manual_pass", with_evidence=True))

    assert report["ok"] is False
    backup = next(item for item in report["results"] if item["id"] == "DB_BACKUP")
    assert backup["ok"] is False
    assert backup["status"] == "fail"


def test_complete_automated_and_manual_evidence_is_go(tmp_path: Path) -> None:
    _prepare_automated_evidence(tmp_path)
    report = _report(tmp_path, _manual_results("manual_pass", with_evidence=True))

    assert report["ok"] is True
    assert report["decision"] == "GO"
    assert all(item["ok"] for item in report["results"] if item["required"])
