"""Gateway configuration is an immutable part of every production release."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_gateway_image_is_pinned_non_root_and_self_contained() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile.gateway").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert (
        "nginxinc/nginx-unprivileged:1.27-alpine@sha256:"
        in dockerfile
    )
    assert "COPY deploy/nginx-gateway.conf.template" in dockerfile
    assert "nginx-gateway.conf.template:/etc/nginx/templates" not in compose
    assert "/etc/nginx/conf.d:size=1m,mode=0777" in compose


def test_rollback_requires_the_previous_gateway_digest() -> None:
    script = (ROOT / "deploy/scripts/rollback.sh").read_text(encoding="utf-8")

    assert "PREVIOUS_ORAL_GATEWAY_IMAGE" in script
    assert "export ORAL_GATEWAY_IMAGE=$PREVIOUS_ORAL_GATEWAY_IMAGE" in script
    assert script.index("stop worker server gateway") < script.index(
        "up -d --remove-orphans"
    )


def test_frontend_and_gateway_base_images_are_digest_pinned() -> None:
    frontend = (ROOT / "deploy/Dockerfile.frontend").read_text(encoding="utf-8")
    gateway = (ROOT / "deploy/Dockerfile.gateway").read_text(encoding="utf-8")

    assert frontend.count("@sha256:") == 3
    assert gateway.count("@sha256:") == 1
