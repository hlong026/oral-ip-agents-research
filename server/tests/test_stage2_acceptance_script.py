import subprocess
from email.message import Message
from pathlib import Path

from scripts import stage2_acceptance


def test_sha256_file_hashes_downloaded_evidence(tmp_path: Path) -> None:
    artifact = tmp_path / "final.mp4"
    artifact.write_bytes(b"stage2 evidence")

    assert stage2_acceptance.sha256_file(artifact) == (
        "83daf0208fd2797aa84fcc5279ad5841ffc347e3b7666d63ed1c024a982a7056"
    )


def test_current_commit_sha_reads_git_without_failing_acceptance(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="abc123\n", stderr="")

    monkeypatch.setattr(stage2_acceptance.subprocess, "run", fake_run)

    assert stage2_acceptance.current_commit_sha(Path("/repo")) == "abc123"


def test_current_commit_sha_degrades_to_unknown(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(returncode=128, cmd=["git"])

    monkeypatch.setattr(stage2_acceptance.subprocess, "run", fake_run)

    assert stage2_acceptance.current_commit_sha(Path("/repo")) == "unknown"


def test_trace_id_is_extracted_case_insensitively() -> None:
    headers = Message()
    headers["x-trace-id"] = "trace-001"

    assert stage2_acceptance.response_trace_id(headers) == "trace-001"


def test_elapsed_ms_since_uses_single_integer_conversion(monkeypatch) -> None:
    monkeypatch.setattr(stage2_acceptance.time, "perf_counter", lambda: 3.25)

    assert stage2_acceptance.elapsed_ms_since(1.0) == 2250


def test_package_evidence_keeps_publish_identity_and_sha(tmp_path: Path) -> None:
    package_path = tmp_path / "douyin-job-001.zip"
    package_path.write_bytes(b"zip bytes")
    job = {
        "id": "job-001",
        "platform": "douyin",
        "status": "success",
        "publicationRevisionId": "rev-001",
        "postId": "post-001",
        "postIdSource": "platform",
        "providerTaskId": "provider-job-001",
    }

    evidence = stage2_acceptance.package_evidence(
        job,
        package_path,
        ["metadata.json", "video.mp4"],
    )

    assert evidence["sha256"] == "5b7a2754b389130e138d57ba83f1eae7f05a41c66becacfa2dd2060143ae66db"
    assert evidence["publicationRevisionId"] == "rev-001"
    assert evidence["postId"] == "post-001"
    assert evidence["postIdSource"] == "platform"
    assert evidence["providerTaskId"] == "provider-job-001"


def test_collect_provider_task_ids_uses_only_available_step_evidence() -> None:
    task = {
        "steps": [
            {"name": "tts", "provider": "hifly", "providerTaskId": "tts-001"},
            {"name": "hd_export", "providerName": "hifly", "provider_task_id": "video-001"},
            {"name": "script_generation", "provider": "openai"},
        ],
        "artifacts": {"avatar_render_task_id": "avatar-001"},
    }

    assert stage2_acceptance.collect_provider_task_ids(task) == [
        {"step": "tts", "provider": "hifly", "taskId": "tts-001", "source": "steps.providerTaskId"},
        {"step": "hd_export", "provider": "hifly", "taskId": "video-001", "source": "steps.provider_task_id"},
        {"step": "artifact", "provider": "", "taskId": "avatar-001", "source": "artifacts.avatar_render_task_id"},
    ]
