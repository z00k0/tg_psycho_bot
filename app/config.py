"""Side-effect-free application settings loading and validation."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.search.normalize import DEFAULT_MAX_QUERY_LENGTH

WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class ConfigError(ValueError):
    """Raised when application settings are missing or invalid."""


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _secret(
    environment: Mapping[str, str],
    *,
    value_name: str,
    file_name: str,
) -> str:
    """Read a secret; an explicitly configured file takes precedence."""

    secret_path = environment.get(file_name, "").strip()
    if secret_path:
        path = Path(secret_path)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"Cannot read secret file configured by {file_name}") from exc
        if not value:
            raise ConfigError(f"Secret file configured by {file_name} is empty")
        return value
    return _required(environment, value_name)


def _integer(
    environment: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = environment.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


def _base_webhook_url(environment: Mapping[str, str]) -> str:
    raw_url = _required(environment, "BASE_WEBHOOK_URL")
    parsed = urlsplit(raw_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError("BASE_WEBHOOK_URL must be an absolute HTTPS URL")
    if parsed.query or parsed.fragment:
        raise ConfigError("BASE_WEBHOOK_URL must not contain a query or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _webhook_path(environment: Mapping[str, str]) -> str:
    path = environment.get("WEBHOOK_PATH", "/webhook").strip()
    if not path.startswith("/") or path == "/" or any(char in path for char in "?#"):
        raise ConfigError("WEBHOOK_PATH must be a non-root absolute URL path")
    return "/" + path.strip("/")


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str = field(repr=False)
    base_webhook_url: str
    webhook_path: str
    webhook_secret: str = field(repr=False)
    host: str
    port: int
    database_path: Path
    search_result_limit: int
    max_query_length: int

    def __repr__(self) -> str:
        return (
            "Settings(bot_token=<redacted>, "
            f"base_webhook_url={self.base_webhook_url!r}, "
            f"webhook_path={self.webhook_path!r}, "
            "webhook_secret=<redacted>, "
            f"host={self.host!r}, port={self.port!r}, "
            f"database_path={self.database_path!r}, "
            f"search_result_limit={self.search_result_limit!r}, "
            f"max_query_length={self.max_query_length!r})"
        )

    @property
    def webhook_url(self) -> str:
        return f"{self.base_webhook_url}{self.webhook_path}"

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environment is None else environment
        bot_token = _secret(
            env,
            value_name="BOT_TOKEN",
            file_name="BOT_TOKEN_FILE",
        )
        webhook_secret = _secret(
            env,
            value_name="WEBHOOK_SECRET",
            file_name="WEBHOOK_SECRET_FILE",
        )
        if not WEBHOOK_SECRET_RE.fullmatch(webhook_secret):
            raise ConfigError(
                "WEBHOOK_SECRET must contain 1-256 ASCII letters, digits, underscores, or hyphens"
            )
        host = env.get("HOST", "0.0.0.0").strip()
        if not host:
            raise ConfigError("HOST must not be empty")
        raw_database_path = env.get(
            "DATABASE_PATH", "data/dictionary.sqlite3"
        ).strip()
        if not raw_database_path:
            raise ConfigError("DATABASE_PATH must not be empty")
        database_path = Path(raw_database_path)
        return cls(
            bot_token=bot_token,
            base_webhook_url=_base_webhook_url(env),
            webhook_path=_webhook_path(env),
            webhook_secret=webhook_secret,
            host=host,
            port=_integer(env, "PORT", 8080, minimum=1, maximum=65535),
            database_path=database_path,
            search_result_limit=_integer(
                env,
                "SEARCH_RESULT_LIMIT",
                5,
                minimum=1,
                maximum=10,
            ),
            max_query_length=_integer(
                env,
                "MAX_QUERY_LENGTH",
                DEFAULT_MAX_QUERY_LENGTH,
                minimum=1,
                maximum=10_000,
            ),
        )
