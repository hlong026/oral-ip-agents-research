"""Frontend Docker builds require workspace apps and shared packages."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_dockerfile_has_a_dedicated_build_context() -> None:
    root_ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    frontend_ignore = (ROOT / "deploy/Dockerfile.frontend.dockerignore").read_text(encoding="utf-8").splitlines()

    assert "apps" in root_ignore
    assert "packages" in root_ignore
    assert "apps" not in frontend_ignore
    assert "packages" not in frontend_ignore
    assert "server" in frontend_ignore
    assert "vendor" in frontend_ignore


def test_frontend_context_keeps_all_workspace_manifests() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile.frontend").read_text(encoding="utf-8")

    assert "COPY . ." in dockerfile
    assert (ROOT / "package.json").exists()
    assert (ROOT / "pnpm-lock.yaml").exists()
    assert (ROOT / "pnpm-workspace.yaml").exists()
    assert (ROOT / "apps/web/package.json").exists()
    assert (ROOT / "apps/admin/package.json").exists()
    assert (ROOT / "packages/types/package.json").exists()
