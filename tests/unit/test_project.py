from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import aiogram
import aiohttp
import pytest
import rapidfuzz

import app.main as main_module
from app.main import build_parser, main


def test_runtime_dependencies_are_importable() -> None:
    assert aiogram.__version__
    assert aiohttp.__version__
    assert rapidfuzz.__version__
    assert sys.version_info >= (3, 14)


def test_packages_are_importable() -> None:
    for module_name in ("app", "app.bot", "app.config", "app.db", "app.search"):
        assert importlib.import_module(module_name)


def test_cli_help_is_available_without_settings(capsys: object) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Telegram psychological dictionary bot" in output


def test_parser_exposes_check_command() -> None:
    arguments = build_parser().parse_args(["check"])
    assert arguments.command == "check"


def test_parser_exposes_webhook_commands() -> None:
    serve = build_parser().parse_args(["serve"])
    delete = build_parser().parse_args(["delete-webhook", "--drop-pending-updates"])

    assert serve.command == "serve"
    assert delete.command == "delete-webhook"
    assert delete.drop_pending_updates is True


def test_serve_command_builds_settings_and_starts_server(
    settings_env: dict[str, str],
    monkeypatch: object,
) -> None:
    for name, value in settings_env.items():
        monkeypatch.setenv(name, value)  # type: ignore[attr-defined]
    received: list[object] = []
    monkeypatch.setattr(main_module, "run_server", received.append)  # type: ignore[attr-defined]

    assert main(["serve"]) == 0
    assert len(received) == 1


def test_delete_webhook_command_is_explicit_and_supports_drop(
    settings_env: dict[str, str],
    monkeypatch: object,
    capsys: object,
) -> None:
    for name, value in settings_env.items():
        monkeypatch.setenv(name, value)  # type: ignore[attr-defined]
    received: list[tuple[object, bool]] = []

    async def fake_delete(settings: object, *, drop_pending_updates: bool) -> None:
        received.append((settings, drop_pending_updates))

    monkeypatch.setattr(  # type: ignore[attr-defined]
        main_module,
        "delete_configured_webhook",
        fake_delete,
    )

    assert main(["delete-webhook", "--drop-pending-updates"]) == 0
    assert received and received[0][1] is True
    assert "Webhook removed" in capsys.readouterr().out  # type: ignore[attr-defined]


@pytest.mark.parametrize("command", [["check"], ["serve"], ["delete-webhook"]])
def test_settings_dependent_commands_reject_invalid_configuration(
    command: list[str],
    settings_env: dict[str, str],
    monkeypatch: object,
) -> None:
    for name, value in settings_env.items():
        monkeypatch.setenv(name, value)  # type: ignore[attr-defined]
    monkeypatch.setenv("BASE_WEBHOOK_URL", "http://insecure.example.test")  # type: ignore[attr-defined]

    with pytest.raises(SystemExit) as captured:
        main(command)

    assert captured.value.code == 2


def test_import_command_rejects_missing_database_argument() -> None:
    with pytest.raises(SystemExit) as captured:
        build_parser().parse_args(["import-dictionary", "dictionary.json", "--database"])

    assert captured.value.code == 2


def test_imports_have_no_filesystem_side_effects(workspace_tmp_path: Path) -> None:
    code = "import app, app.bot, app.config, app.db, app.search"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=workspace_tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert list(workspace_tmp_path.iterdir()) == []
