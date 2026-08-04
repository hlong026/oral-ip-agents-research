"""Tencent Cloud production deployment contract tests."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))


def test_production_compose_uses_external_data_services() -> None:
    services = _compose()["services"]

    assert {"gateway", "web", "admin", "server", "worker", "migration", "cos-migration"} <= set(services)
    assert {"postgres", "redis", "minio", "im-listener"}.isdisjoint(services)
    assert set(services["gateway"]["ports"]) == ["${GATEWAY_BIND:-127.0.0.1:8080}:8080"]
    for name in ("server", "worker", "web", "admin"):
        assert "ports" not in services[name]


def test_api_worker_and_migrations_use_the_same_server_image() -> None:
    services = _compose()["services"]
    expected = "${ORAL_SERVER_IMAGE:?ORAL_SERVER_IMAGE is required}"

    assert services["server"]["image"] == expected
    assert services["worker"]["image"] == expected
    assert services["migration"]["image"] == expected
    assert services["cos-migration"]["image"] == expected
    assert services["migration"]["command"] == ["alembic", "upgrade", "head"]
    assert services["migration"]["profiles"] == ["migration"]
    assert services["cos-migration"]["profiles"] == ["cos-migration"]
    assert services["cos-migration"]["command"][:4] == [
        "python",
        "-m",
        "scripts.migrate_storage_to_cos",
        "--resume",
    ]


def test_production_compose_has_restart_health_and_log_guards() -> None:
    services = _compose()["services"]

    for name in ("gateway", "web", "admin", "server", "worker"):
        assert services[name]["restart"] == "unless-stopped"
    for name in ("gateway", "web", "admin", "server"):
        assert "healthcheck" in services[name]
    assert services["server"]["logging"]["options"] == {
        "max-size": "20m",
        "max-file": "5",
    }
    assert "/tmp:size=1g,mode=1777" in services["server"]["tmpfs"]
    assert services["server"]["shm_size"] == "1gb"


def test_production_files_contain_no_embedded_credentials() -> None:
    targets = [
        ROOT / "docker-compose.prod.yml",
        ROOT / "deploy/.env.prod.example",
        ROOT / "deploy/nginx-gateway.conf.template",
        ROOT / "deploy/scripts/deploy.sh",
        ROOT / "deploy/scripts/rollback.sh",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in targets)

    assert "oral_dev_pass" not in combined
    assert "oral_dev_minio" not in combined
    assert not re.search(r"SecretKey\s*=\s*[A-Za-z0-9/+]{20,}", combined)
    assert "PUBLISH_SESSION_ENCRYPTION_KEY=" not in combined


def test_gateway_routes_api_media_websocket_and_both_frontends() -> None:
    config = (ROOT / "deploy/nginx-gateway.conf.template").read_text(encoding="utf-8")

    assert "server_name ${WEB_HOST}" in config
    assert "server_name ${ADMIN_HOST}" in config
    assert "proxy_pass http://oral_api" in config
    assert "proxy_pass http://oral_web" in config
    assert "proxy_pass http://oral_admin" in config
    assert "media/" in config
    assert "ws/" in config
    assert "proxy_set_header Upgrade $http_upgrade" in config
    assert "proxy_request_buffering off" in config
    assert "proxy_buffering off" in config
    assert "X-Forwarded-Proto https" in config


def test_frontend_images_are_reproducible_and_non_root_runtime() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile.frontend").read_text(encoding="utf-8")

    assert "node:22.22.0-alpine" in dockerfile
    assert "pnpm@9.15.0" in dockerfile
    assert "pnpm install --frozen-lockfile" in dockerfile
    assert "--filter @oral/web build" in dockerfile
    assert "--filter @oral/admin build" in dockerfile
    assert dockerfile.count("nginxinc/nginx-unprivileged:1.27-alpine") == 2
    assert "FROM workspace AS web-build" in dockerfile
    assert "FROM workspace AS admin-build" in dockerfile


def test_deploy_runs_migration_before_start_and_requires_digests() -> None:
    script = (ROOT / "deploy/scripts/deploy.sh").read_text(encoding="utf-8")

    migration = script.index("run --rm --no-deps migration")
    startup = script.index("up -d --remove-orphans")
    assert migration < startup
    assert "@sha256" in script
    assert "assert payload.get(\"env\") == \"prod\"" in script
    assert "storage.get(\"driver\") == \"s3\"" in script
    assert "set -x" not in script


def test_rollback_never_downgrades_database_automatically() -> None:
    script = (ROOT / "deploy/scripts/rollback.sh").read_text(encoding="utf-8")

    assert "ROLLBACK_SCHEMA_COMPATIBLE" in script
    assert "alembic downgrade" not in script
    assert "PREVIOUS_ORAL_SERVER_IMAGE" in script
    assert "@sha256" in script
    assert "set -x" not in script


def test_lifecycle_plan_is_non_executable_and_scoped() -> None:
    plan = yaml.safe_load(
        (ROOT / "deploy/tencent-cos/lifecycle-plan.example.json").read_text(encoding="utf-8")
    )

    assert plan["applyAutomatically"] is False
    assert any(rule["action"] == "abortIncompleteMultipartUpload" for rule in plan["rules"])
    assert all(rule.get("prefix", "") != "*" for rule in plan["rules"])
