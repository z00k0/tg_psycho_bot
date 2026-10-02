from __future__ import annotations

import sqlite3

import pytest

from app.db.capabilities import SqliteCapabilityError, check_sqlite_fts5_trigram


class BrokenConnection:
    closed = False

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
        raise sqlite3.OperationalError("no such tokenizer: trigram")

    def close(self) -> None:
        self.closed = True


def test_runtime_supports_fts5_trigram() -> None:
    check_sqlite_fts5_trigram()


def test_probe_wraps_sqlite_error_and_closes_connection() -> None:
    connection = BrokenConnection()

    with pytest.raises(SqliteCapabilityError, match="FTS5.*trigram"):
        check_sqlite_fts5_trigram(lambda _: connection)

    assert connection.closed is True
