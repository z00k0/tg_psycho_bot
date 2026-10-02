from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def workspace_tmp_path() -> Iterator[Path]:
    root = Path.cwd() / "data" / ".test-runtime"
    path = root / uuid4().hex
    path.mkdir(parents=True)
    yield path
    for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if child.is_dir():
            child.rmdir()
        else:
            child.unlink()
    path.rmdir()
    if root.exists() and not any(root.iterdir()):
        root.rmdir()


@pytest.fixture
def settings_env(workspace_tmp_path: Path) -> dict[str, str]:
    return {
        "BOT_TOKEN": "123456:unit-test-token",
        "BASE_WEBHOOK_URL": "https://bot.example.test",
        "WEBHOOK_PATH": "/telegram/webhook",
        "WEBHOOK_SECRET": "unit_test-secret",
        "HOST": "127.0.0.1",
        "PORT": "8081",
        "DATABASE_PATH": str(workspace_tmp_path / "dictionary.sqlite3"),
        "SEARCH_RESULT_LIMIT": "5",
        "MAX_QUERY_LENGTH": "200",
    }
