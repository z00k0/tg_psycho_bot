"""Versioned and atomic SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files

from app.db.connection import transaction

LATEST_SCHEMA_VERSION = 1

MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class MigrationError(RuntimeError):
    """Raised when migrations are invalid or cannot be applied atomically."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


def _schema_sql() -> str:
    return files("app.db").joinpath("schema.sql").read_text(encoding="utf-8")


def default_migrations() -> tuple[Migration, ...]:
    return (Migration(LATEST_SCHEMA_VERSION, "initial_dictionary_schema", _schema_sql()),)


def _migration_table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("schema_migrations",),
    ).fetchone()
    return row is not None


def get_schema_version(connection: sqlite3.Connection) -> int:
    """Return the latest applied schema version, or zero for an empty DB."""

    if not _migration_table_exists(connection):
        return 0
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
    ).fetchone()
    return int(row["version"] if isinstance(row, sqlite3.Row) else row[0])


def _validate_migrations(migrations: Sequence[Migration]) -> None:
    versions = [migration.version for migration in migrations]
    if any(version < 1 for version in versions):
        raise MigrationError("Migration versions must be positive integers")
    if versions != sorted(set(versions)):
        raise MigrationError("Migrations must have unique versions in ascending order")
    if any(not migration.name.strip() or not migration.sql.strip() for migration in migrations):
        raise MigrationError("Migration name and SQL must not be empty")


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration] | None = None,
) -> int:
    """Apply pending migrations in one transaction and return the version."""

    selected = tuple(default_migrations() if migrations is None else migrations)
    _validate_migrations(selected)
    latest_available = selected[-1].version if selected else 0
    current_version = get_schema_version(connection)
    if current_version > latest_available:
        raise MigrationError(
            f"Database schema version {current_version} is newer than supported "
            f"version {latest_available}"
        )
    pending = [item for item in selected if item.version > current_version]
    if not pending:
        return current_version

    try:
        with transaction(connection):
            connection.execute(MIGRATION_TABLE_SQL)
            for migration in pending:
                connection.executescript(migration.sql)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                    (migration.version, migration.name),
                )
    except sqlite3.Error as exc:
        raise MigrationError(
            f"Failed to apply database migration {pending[0].version}"
        ) from exc
    return get_schema_version(connection)
