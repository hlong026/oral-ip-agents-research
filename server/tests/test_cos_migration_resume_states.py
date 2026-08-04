"""Only successful COS manifest states are resumable."""

from scripts.cos_migration import Manifest


def test_resume_only_skips_successful_manifest_states(tmp_path) -> None:
    manifest = Manifest(tmp_path / "manifest.jsonl")
    manifest.append({"key": "planned.mp4", "status": "planned"})
    manifest.append({"key": "failed.mp4", "status": "error"})
    manifest.append({"key": "copied.mp4", "status": "copied"})
    manifest.append({"key": "verified.mp4", "status": "verified"})
    manifest.append({"key": "existing.mp4", "status": "skipped_existing"})

    assert manifest.completed_keys() == {
        "copied.mp4",
        "verified.mp4",
        "existing.mp4",
    }
