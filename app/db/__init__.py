"""SQLite persistence layer."""

from app.db.capabilities import SqliteCapabilityError, check_sqlite_fts5_trigram
from app.db.connection import database_connection, open_database, transaction
from app.db.import_dictionary import (
    DictionaryEntry,
    DictionaryImportError,
    DictionaryPayload,
    ImportReport,
    import_dictionary_file,
    import_dictionary_payload,
    load_dictionary_json,
)
from app.db.migrate import (
    LATEST_SCHEMA_VERSION,
    Migration,
    MigrationError,
    apply_migrations,
    get_schema_version,
)
from app.db.repository import DictionaryRepository

__all__ = [
    "LATEST_SCHEMA_VERSION",
    "DictionaryEntry",
    "DictionaryImportError",
    "DictionaryPayload",
    "DictionaryRepository",
    "ImportReport",
    "Migration",
    "MigrationError",
    "SqliteCapabilityError",
    "apply_migrations",
    "check_sqlite_fts5_trigram",
    "database_connection",
    "get_schema_version",
    "import_dictionary_file",
    "import_dictionary_payload",
    "load_dictionary_json",
    "open_database",
    "transaction",
]
