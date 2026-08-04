"""Production release manifests bind code, images, database and COS identity."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIGEST_PATTERN = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


def test_release_manifest_is_complete_and_secret_free() -> None:
    path = ROOT / "deploy/release-manifest.example.json"
    text = path.read_text(encoding="utf-8")
    manifest = json.loads(text)

    assert manifest["schemaVersion"] == 1
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["gitCommit"])
    assert set(manifest["images"]) == {"server", "gateway", "web", "admin"}
    assert all(DIGEST_PATTERN.fullmatch(image) for image in manifest["images"].values())
    assert manifest["database"]["alembicRevision"]
    assert manifest["database"]["backupId"]
    assert manifest["storage"]["driver"] == "s3"
    assert manifest["storage"]["endpointHost"].endswith(".myqcloud.com")
    assert manifest["storage"]["bucket"].rsplit("-", 1)[-1].isdigit()
    assert manifest["approvedBy"]
    assert "SecretId" not in text
    assert "SecretKey" not in text
    assert "access_key" not in text.lower()
    assert "secret_key" not in text.lower()
