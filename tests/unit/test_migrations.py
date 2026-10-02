from __future__ import annotations

import sqlite3

import pytest

from app.db.connection import database_connection
from app.db.migrate import (
    LATEST_SCHEMA_VERSION,
    Migration,
    MigrationError,
    apply_migrations,
    get_schema_version,
)

EXPECTED_OBJECTS = {
    "schema_migrations",
    "term_aliases",
    "terms",
    "terms_fts",
    "terms_fts_after_delete",
    "terms_fts_after_insert",
    "terms_fts_after_update",
}


def insert_term(
    connection: sqlite3.Connection,
    *,
    term_id: int = 1,
    term: str = "АБСТРАКЦИЯ",
    normalized: str = "абстракция",
) -> None:
    connection.execute(
        """
        INSERT INTO terms(
            id, term, term_normalized, heading, definition,
            redirect_to, letter, search_blob, quality_flags_json
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, '[]')
        """,
        (
            term_id,
            term,
            normalized,
            term,
            f"Определение термина {term}",
            term[0],
            normalized,
        ),
    )


def fts_ids(connection: sqlite3.Connection, query: str) -> list[int]:
    rows = connection.execute(
        "SELECT rowid FROM terms_fts WHERE terms_fts MATCH ? ORDER BY rowid",
        (query,),
    ).fetchall()
    return [int(row[0]) for row in rows]


def test_migration_creates_schema_objects() -> None:
    with database_connection(":memory:") as connection:
        assert get_schema_version(connection) == 0

        version = apply_migrations(connection)

        rows = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type IN ('table', 'trigger') AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
        names = {str(row[0]) for row in rows}
        assert names >= EXPECTED_OBJECTS
        assert version == get_schema_version(connection) == LATEST_SCHEMA_VERSION


def test_migrations_are_idempotent() -> None:
    with database_connection(":memory:") as connection:
        assert apply_migrations(connection) == LATEST_SCHEMA_VERSION
        first_rows = connection.execute(
            "SELECT version, name, applied_at FROM schema_migrations"
        ).fetchall()

        assert apply_migrations(connection) == LATEST_SCHEMA_VERSION
        second_rows = connection.execute(
            "SELECT version, name, applied_at FROM schema_migrations"
        ).fetchall()

        assert [tuple(row) for row in second_rows] == [tuple(row) for row in first_rows]


def test_insert_trigger_adds_fts_entry() -> None:
    with database_connection(":memory:") as connection:
        apply_migrations(connection)

        insert_term(connection)

        assert fts_ids(connection, "страк") == [1]


def test_update_trigger_replaces_fts_entry() -> None:
    with database_connection(":memory:") as connection:
        apply_migrations(connection)
        insert_term(connection)

        connection.execute(
            """
            UPDATE terms
            SET term = 'МЫШЛЕНИЕ', heading = 'МЫШЛЕНИЕ',
                definition = 'Определение мышления', search_blob = 'мышление'
            WHERE id = 1
            """
        )

        assert fts_ids(connection, "страк") == []
        assert fts_ids(connection, "мышл") == [1]


def test_delete_trigger_removes_fts_entry() -> None:
    with database_connection(":memory:") as connection:
        apply_migrations(connection)
        insert_term(connection)

        connection.execute("DELETE FROM terms WHERE id = 1")

        assert fts_ids(connection, "страк") == []


def test_normalized_term_is_unique() -> None:
    with database_connection(":memory:") as connection:
        apply_migrations(connection)
        insert_term(connection)

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            insert_term(connection, term_id=2, term="ДРУГОЙ", normalized="абстракция")


def test_aliases_are_deleted_with_term() -> None:
    with database_connection(":memory:") as connection:
        apply_migrations(connection)
        insert_term(connection)
        connection.execute(
            "INSERT INTO term_aliases(term_id, alias_normalized) VALUES (1, 'абстр')"
        )

        connection.execute("DELETE FROM terms WHERE id = 1")

        assert connection.execute("SELECT COUNT(*) FROM term_aliases").fetchone()[0] == 0


def test_failed_migration_rolls_back_every_schema_change() -> None:
    broken = Migration(
        1,
        "broken",
        "CREATE TABLE partial(value TEXT); CREATE TABLE invalid(",
    )
    with database_connection(":memory:") as connection:
        with pytest.raises(MigrationError, match="migration 1"):
            apply_migrations(connection, (broken,))

        assert get_schema_version(connection) == 0
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'partial'"
        ).fetchone() is None
        assert connection.in_transaction is False


@pytest.mark.parametrize(
    "migrations",
    [
        (Migration(0, "zero", "SELECT 1"),),
        (Migration(2, "two", "SELECT 1"), Migration(1, "one", "SELECT 1")),
        (Migration(1, "one", "SELECT 1"), Migration(1, "duplicate", "SELECT 1")),
        (Migration(1, "", "SELECT 1"),),
        (Migration(1, "empty", "  "),),
    ],
)
def test_rejects_invalid_migration_sequence(migrations: tuple[Migration, ...]) -> None:
    with database_connection(":memory:") as connection, pytest.raises(MigrationError):
        apply_migrations(connection, migrations)
