from __future__ import annotations

from pathlib import Path

import pytest

from app.db.connection import database_connection, open_database, transaction


def test_memory_connection_enables_required_pragmas() -> None:
    with database_connection(":memory:", busy_timeout_ms=1_234) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1_234
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "memory"
        row = connection.execute("SELECT 42 AS answer").fetchone()
        assert row["answer"] == 42


def test_file_connection_creates_parent_and_enables_wal(
    workspace_tmp_path: Path,
) -> None:
    database_path = workspace_tmp_path / "nested" / "dictionary.sqlite3"

    with database_connection(database_path) as connection:
        assert database_path.exists()
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1


@pytest.mark.parametrize("value", [-1, True, 1.5, "5000"])
def test_rejects_invalid_busy_timeout(value: object) -> None:
    with pytest.raises(ValueError, match="busy_timeout_ms"):
        open_database(":memory:", busy_timeout_ms=value)  # type: ignore[arg-type]


def test_transaction_commits_successful_block() -> None:
    with database_connection(":memory:") as connection:
        connection.execute("CREATE TABLE example(value TEXT)")

        with transaction(connection):
            connection.execute("INSERT INTO example VALUES ('saved')")

        assert connection.execute("SELECT value FROM example").fetchone()[0] == "saved"


def test_transaction_rolls_back_failed_block() -> None:
    with database_connection(":memory:") as connection:
        connection.execute("CREATE TABLE example(value TEXT)")

        with pytest.raises(RuntimeError, match="stop"), transaction(connection):
            connection.execute("INSERT INTO example VALUES ('discarded')")
            raise RuntimeError("stop")

        assert connection.execute("SELECT COUNT(*) FROM example").fetchone()[0] == 0


def test_rejects_nested_transactions() -> None:
    with (
        database_connection(":memory:") as connection,
        transaction(connection),
        pytest.raises(RuntimeError, match="Nested"),
        transaction(connection),
    ):
        pass
