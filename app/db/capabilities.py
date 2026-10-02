"""Runtime checks for SQLite features required by the application."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Protocol


class ConnectionLike(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object: ...

    def close(self) -> None: ...


ConnectFactory = Callable[[str], ConnectionLike]


class SqliteCapabilityError(RuntimeError):
    """Raised when the SQLite runtime lacks a required feature."""


def check_sqlite_fts5_trigram(
    connect: ConnectFactory = sqlite3.connect,
) -> None:
    """Fail fast unless SQLite supports FTS5 with the trigram tokenizer."""

    connection: ConnectionLike | None = None
    try:
        connection = connect(":memory:")
        connection.execute(
            "CREATE VIRTUAL TABLE fts5_trigram_probe "
            "USING fts5(value, tokenize='trigram')"
        )
    except sqlite3.Error as exc:
        raise SqliteCapabilityError(
            "SQLite must support FTS5 with the trigram tokenizer"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
