"""Safe structured logging for production and tests."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

REDACTED = "<redacted>"
STRUCTURED_FIELDS = (
    "event",
    "strategy",
    "duration_ms",
    "result_count",
    "normalized_length",
    "error_type",
)


def _redact(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, tuple):
        return tuple(_redact(item, secrets) for item in value)
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, Mapping):
        return {key: _redact(item, secrets) for key, item in value.items()}
    return value


class SecretRedactionFilter(logging.Filter):
    """Remove configured credentials from messages and interpolation arguments."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(
            sorted({value for value in secrets if value}, key=len, reverse=True)
        )

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.msg, self._secrets)
        record.args = _redact(record.args, self._secrets)
        return True


class JsonLogFormatter(logging.Formatter):
    """Emit one compact JSON object and omit exception messages by design."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field_name in STRUCTURED_FIELDS:
            if hasattr(record, field_name):
                payload[field_name] = getattr(record, field_name)
        if record.exc_info is not None and "error_type" not in payload:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(*, secrets: Iterable[str] = (), level: int = logging.INFO) -> None:
    """Configure the application logger without changing third-party loggers."""

    logger = logging.getLogger("tg_psyco")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter(secrets))
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
