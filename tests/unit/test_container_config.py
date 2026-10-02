from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]


def test_dockerfile_is_multistage_locked_and_non_root() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("FROM python:3.14.7-slim-bookworm") == 2
    assert " AS builder" in dockerfile
    assert " AS runtime" in dockerfile
    assert 'python -m pip install "poetry==2.2.1"' in dockerfile
    assert "poetry check --lock" in dockerfile
    assert "poetry install --only main" in dockerfile
    assert "COPY --from=builder" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'CMD ["tg-psyco", "serve"]' in dockerfile


def test_runtime_stage_does_not_install_build_tools_or_poetry() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split(" AS runtime", maxsplit=1)[1]

    assert "apt-get" not in runtime
    assert "pip install" not in runtime
    assert "poetry install" not in runtime
    assert "COPY --from=builder" in runtime


def test_dockerignore_excludes_secrets_databases_sources_and_tests() -> None:
    patterns = set((PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())

    assert {".git", ".venv", ".env", "secrets", "tests", "data"} <= patterns
    assert {"*.doc", "*.txt", "*.pdf", "*.sqlite3"} <= patterns


def test_caddy_only_proxies_to_internal_bot_with_health_check() -> None:
    caddyfile = (PROJECT_ROOT / "Caddyfile").read_text(encoding="utf-8")

    assert "{$BOT_DOMAIN}" in caddyfile
    assert "reverse_proxy bot:8080" in caddyfile
    assert "health_uri /healthz" in caddyfile


def _compose_config(*files: str) -> dict[str, object]:
    environment = os.environ.copy()
    environment["BOT_DOMAIN"] = "bot.example.test"
    arguments = ["docker", "compose"]
    for filename in files:
        arguments.extend(("-f", filename))
    arguments.extend(("config", "--format", "json"))
    result = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI is unavailable")
def test_base_compose_is_for_existing_nginx_and_binds_bot_to_loopback() -> None:
    configuration = _compose_config("docker-compose.yaml")
    services = configuration["services"]

    assert "caddy" not in services
    assert services["bot"]["ports"] == [
        {
            "mode": "ingress",
            "target": 8080,
            "published": "8080",
            "protocol": "tcp",
            "host_ip": "127.0.0.1",
        }
    ]
    assert services["bot"]["read_only"] is True
    assert services["bot"]["deploy"]["replicas"] == 1
    assert services["bot"]["restart"] == "unless-stopped"
    assert services["bot"]["stop_grace_period"] == "30s"
    assert services["bot"]["cap_drop"] == ["ALL"]
    assert services["bot"]["tmpfs"]
    assert services["bot"]["secrets"]
    assert set(services) == {"bot"}


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI is unavailable")
def test_optional_caddy_override_publishes_only_http_and_https() -> None:
    configuration = _compose_config(
        "docker-compose.yaml",
        "docker-compose.caddy.yaml",
    )
    services = configuration["services"]

    assert services["caddy"]["read_only"] is True
    assert services["caddy"]["depends_on"]["bot"]["condition"] == "service_healthy"
    published = {port["published"] for port in services["caddy"]["ports"]}
    assert published == {"80", "443"}


def test_compose_source_contains_no_secret_values() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")

    assert "BOT_TOKEN:" not in compose
    assert "WEBHOOK_SECRET:" not in compose
    assert "BOT_TOKEN_FILE: /run/secrets/bot_token" in compose
    assert "WEBHOOK_SECRET_FILE: /run/secrets/webhook_secret" in compose
