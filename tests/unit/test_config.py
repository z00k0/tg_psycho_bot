from __future__ import annotations

from pathlib import Path

import pytest

from app.config import ConfigError, Settings


def test_loads_valid_settings(
    settings_env: dict[str, str], workspace_tmp_path: Path
) -> None:
    settings = Settings.from_env(settings_env)

    assert settings.bot_token == "123456:unit-test-token"
    assert settings.webhook_url == "https://bot.example.test/telegram/webhook"
    assert settings.database_path == workspace_tmp_path / "dictionary.sqlite3"
    assert settings.port == 8081


@pytest.mark.parametrize("missing", ["BOT_TOKEN", "BASE_WEBHOOK_URL", "WEBHOOK_SECRET"])
def test_rejects_missing_required_setting(
    settings_env: dict[str, str], missing: str
) -> None:
    settings_env.pop(missing)

    with pytest.raises(ConfigError, match=missing):
        Settings.from_env(settings_env)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("BASE_WEBHOOK_URL", "http://bot.example.test", "HTTPS"),
        ("BASE_WEBHOOK_URL", "https://bot.example.test/?debug=1", "query"),
        ("WEBHOOK_PATH", "webhook", "absolute"),
        ("WEBHOOK_PATH", "/", "non-root"),
        ("WEBHOOK_SECRET", "bad secret", "ASCII"),
        ("PORT", "0", "between"),
        ("PORT", "not-a-number", "integer"),
        ("DATABASE_PATH", "  ", "must not be empty"),
    ],
)
def test_rejects_invalid_setting(
    settings_env: dict[str, str], name: str, value: str, message: str
) -> None:
    settings_env[name] = value

    with pytest.raises(ConfigError, match=message):
        Settings.from_env(settings_env)


def test_secret_files_take_precedence(
    settings_env: dict[str, str], workspace_tmp_path: Path
) -> None:
    token_file = workspace_tmp_path / "bot_token"
    secret_file = workspace_tmp_path / "webhook_secret"
    token_file.write_text("file-token\n", encoding="utf-8")
    secret_file.write_text("file_secret-123\n", encoding="utf-8")
    settings_env["BOT_TOKEN_FILE"] = str(token_file)
    settings_env["WEBHOOK_SECRET_FILE"] = str(secret_file)

    settings = Settings.from_env(settings_env)

    assert settings.bot_token == "file-token"
    assert settings.webhook_secret == "file_secret-123"


def test_rejects_missing_secret_file(
    settings_env: dict[str, str], workspace_tmp_path: Path
) -> None:
    settings_env["BOT_TOKEN_FILE"] = str(workspace_tmp_path / "missing")

    with pytest.raises(ConfigError, match="BOT_TOKEN_FILE"):
        Settings.from_env(settings_env)


def test_rejects_empty_secret_file(
    settings_env: dict[str, str], workspace_tmp_path: Path
) -> None:
    token_file = workspace_tmp_path / "empty"
    token_file.write_text("  \n", encoding="utf-8")
    settings_env["BOT_TOKEN_FILE"] = str(token_file)

    with pytest.raises(ConfigError, match="empty"):
        Settings.from_env(settings_env)


def test_repr_redacts_secrets(settings_env: dict[str, str]) -> None:
    settings = Settings.from_env(settings_env)
    rendered = repr(settings)

    assert "123456:unit-test-token" not in rendered
    assert "unit_test-secret" not in rendered
    assert rendered.count("<redacted>") == 2
