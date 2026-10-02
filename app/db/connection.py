"""SQLite connection setup and explicit transaction management."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from os import PathLike
from pathlib import Path

DEFAULT_BUSY_TIMEOUT_MS = 5_000
MEMORY_DATABASE = ":memory:"


def _database_name(path: str | PathLike[str]) -> str:
    return str(path)


def _is_memory_database(database: str, *, uri: bool) -> bool:
    return database == MEMORY_DATABASE or (uri and "mode=memory" in database)


def open_database(
    path: str | PathLike[str],
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    uri: bool = False,
) -> sqlite3.Connection:
    """Open and configure a SQLite connection for the application.

    The connection stays in SQLite autocommit mode. Mutating multi-statement
    operations must use :func:`transaction` to define their boundary.
    """

    if (
        not isinstance(busy_timeout_ms, int)
        or isinstance(busy_timeout_ms, bool)
        or busy_timeout_ms < 0
    ):
        raise ValueError("busy_timeout_ms must be a non-negative integer")

    database = _database_name(path)
    is_memory = _is_memory_database(database, uri=uri)
    if not is_memory and not uri:
        Path(database).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        database,
        timeout=busy_timeout_ms / 1_000,
        autocommit=True,
        uri=uri,
    )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        if not is_memory:
            journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                raise sqlite3.OperationalError("SQLite did not enable WAL journal mode")
            connection.execute("PRAGMA synchronous = NORMAL")
    except Exception:
        connection.close()
        raise
    return connection


@contextmanager
def database_connection(
    path: str | PathLike[str],
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    uri: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Yield a configured connection and always close it afterwards."""

    connection = open_database(path, busy_timeout_ms=busy_timeout_ms, uri=uri)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(
    connection: sqlite3.Connection,
    *,
    immediate: bool = True,
) -> Iterator[sqlite3.Connection]:
    """Run a block in an explicit transaction and commit or roll it back."""

    if connection.in_transaction:
        raise RuntimeError("Nested transactions are not supported")
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")
