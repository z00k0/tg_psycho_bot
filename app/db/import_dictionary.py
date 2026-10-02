"""Validate and atomically import the dictionary JSON into SQLite."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.capabilities import SqliteCapabilityError, check_sqlite_fts5_trigram
from app.db.connection import database_connection, transaction
from app.db.migrate import MigrationError, apply_migrations
from app.search.normalize import QueryNormalizationError, normalize_query

SUPPORTED_JSON_SCHEMA_VERSION = 1
DEFAULT_JSON_PATH = Path("psychological_dictionary.json")
DEFAULT_DATABASE_PATH = Path("data/dictionary.sqlite3")


class DictionaryImportError(ValueError):
    """Raised when dictionary input is invalid or cannot be imported safely."""


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    id: int
    term: str
    term_normalized: str
    aliases: tuple[str, ...]
    letter: str
    heading: str
    definition: str
    redirect_to: str | None
    quality_flags: tuple[str, ...]

    @property
    def search_blob(self) -> str:
        return " ".join((self.term_normalized, *self.aliases))


@dataclass(frozen=True, slots=True)
class DictionaryPayload:
    schema_version: int
    entries: tuple[DictionaryEntry, ...]


@dataclass(frozen=True, slots=True)
class ImportReport:
    term_count: int
    alias_count: int
    fts_count: int


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DictionaryImportError(f"{location} must be an object")
    return value


def _required(mapping: Mapping[str, Any], field: str, location: str) -> Any:
    if field not in mapping:
        raise DictionaryImportError(f"{location}.{field} is required")
    return mapping[field]


def _positive_integer(value: object, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise DictionaryImportError(f"{location} must be a positive integer")
    return value


def _nonempty_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DictionaryImportError(f"{location} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, location: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, location)


def _string_list(value: object, location: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise DictionaryImportError(f"{location} must be {qualifier} of strings")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_nonempty_string(item, f"{location}[{index}]"))
    return tuple(result)


def _canonical(value: str, location: str) -> str:
    try:
        # The 200-character default protects bot input. Source dictionary
        # records may legitimately be longer and must not inherit that UI
        # boundary. The multiplier also covers Unicode case-fold expansion.
        return normalize_query(value, max_length=max(1, len(value) * 4))
    except QueryNormalizationError as exc:
        raise DictionaryImportError(f"{location} is not a valid search term") from exc


def _entry(value: object, index: int) -> DictionaryEntry:
    location = f"entries[{index}]"
    source = _mapping(value, location)
    entry_id = _positive_integer(_required(source, "id", location), f"{location}.id")
    term = _nonempty_string(_required(source, "term", location), f"{location}.term")
    source_normalized = _nonempty_string(
        _required(source, "term_normalized", location),
        f"{location}.term_normalized",
    )
    term_normalized = _canonical(source_normalized, f"{location}.term_normalized")
    if term_normalized != _canonical(term, f"{location}.term"):
        raise DictionaryImportError(
            f"{location}.term_normalized does not match the normalized term"
        )

    raw_search_terms = _string_list(
        _required(source, "search_terms", location),
        f"{location}.search_terms",
        allow_empty=False,
    )
    seen = {term_normalized}
    aliases: list[str] = []
    for search_index, search_term in enumerate(raw_search_terms):
        normalized = _canonical(
            search_term,
            f"{location}.search_terms[{search_index}]",
        )
        if normalized not in seen:
            seen.add(normalized)
            aliases.append(normalized)

    letter = _nonempty_string(
        _required(source, "letter", location), f"{location}.letter"
    )
    if len(letter) != 1:
        raise DictionaryImportError(f"{location}.letter must contain one character")
    heading = _nonempty_string(
        _required(source, "heading", location), f"{location}.heading"
    )
    definition = _nonempty_string(
        _required(source, "definition", location), f"{location}.definition"
    )
    redirect_to = _optional_string(
        _required(source, "redirect_to", location), f"{location}.redirect_to"
    )
    quality_flags = _string_list(
        _required(source, "quality_flags", location),
        f"{location}.quality_flags",
        allow_empty=True,
    )
    return DictionaryEntry(
        id=entry_id,
        term=term,
        term_normalized=term_normalized,
        aliases=tuple(aliases),
        letter=letter,
        heading=heading,
        definition=definition,
        redirect_to=redirect_to,
        quality_flags=quality_flags,
    )


def parse_dictionary_payload(value: object) -> DictionaryPayload:
    """Validate an already decoded JSON value without touching SQLite."""

    source = _mapping(value, "root")
    schema_version = _positive_integer(
        _required(source, "schema_version", "root"), "schema_version"
    )
    if schema_version != SUPPORTED_JSON_SCHEMA_VERSION:
        raise DictionaryImportError(
            f"Unsupported dictionary schema_version {schema_version}; "
            f"expected {SUPPORTED_JSON_SCHEMA_VERSION}"
        )
    raw_entries = _required(source, "entries", "root")
    if not isinstance(raw_entries, list):
        raise DictionaryImportError("entries must be a list")
    expected_count = _positive_integer(
        _required(source, "entry_count", "root"), "entry_count"
    )
    if expected_count != len(raw_entries):
        raise DictionaryImportError(
            f"entry_count is {expected_count}, but entries contains {len(raw_entries)} records"
        )

    entries = tuple(_entry(item, index) for index, item in enumerate(raw_entries))
    ids: set[int] = set()
    normalized_terms: set[str] = set()
    for entry in entries:
        if entry.id in ids:
            raise DictionaryImportError(f"Duplicate entry id {entry.id}")
        if entry.term_normalized in normalized_terms:
            raise DictionaryImportError(
                f"Duplicate normalized term {entry.term_normalized!r}"
            )
        ids.add(entry.id)
        normalized_terms.add(entry.term_normalized)
    return DictionaryPayload(schema_version=schema_version, entries=entries)


def load_dictionary_json(path: str | Path) -> DictionaryPayload:
    """Read and fully validate a dictionary JSON file."""

    source_path = Path(path)
    try:
        decoded = json.loads(source_path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise DictionaryImportError(f"Cannot read dictionary file: {source_path}") from exc
    except json.JSONDecodeError as exc:
        raise DictionaryImportError(f"Dictionary file is not valid JSON: {source_path}") from exc
    return parse_dictionary_payload(decoded)


def _quality_flags_json(flags: Sequence[str]) -> str:
    return json.dumps(list(flags), ensure_ascii=False, separators=(",", ":"))


def _current_counts(connection: sqlite3.Connection) -> ImportReport:
    term_count = int(connection.execute("SELECT COUNT(*) FROM terms").fetchone()[0])
    alias_count = int(
        connection.execute("SELECT COUNT(*) FROM term_aliases").fetchone()[0]
    )
    fts_count = int(
        connection.execute("SELECT COUNT(*) FROM terms_fts_docsize").fetchone()[0]
    )
    return ImportReport(term_count, alias_count, fts_count)


def _verify_import(
    connection: sqlite3.Connection,
    *,
    expected_terms: int,
    expected_aliases: int,
) -> ImportReport:
    report = _current_counts(connection)
    if report.term_count != expected_terms:
        raise DictionaryImportError(
            f"Imported term count mismatch: {report.term_count} != {expected_terms}"
        )
    if report.alias_count != expected_aliases:
        raise DictionaryImportError(
            f"Imported alias count mismatch: {report.alias_count} != {expected_aliases}"
        )
    if report.fts_count != expected_terms:
        raise DictionaryImportError(
            f"FTS index count mismatch: {report.fts_count} != {expected_terms}"
        )
    connection.execute(
        "INSERT INTO terms_fts(terms_fts, rank) VALUES ('integrity-check', 1)"
    )
    return report


def import_dictionary_payload(
    connection: sqlite3.Connection,
    payload: DictionaryPayload,
) -> ImportReport:
    """Atomically replace all dictionary records with a validated payload."""

    expected_aliases = sum(len(entry.aliases) for entry in payload.entries)
    try:
        with transaction(connection):
            connection.execute("DELETE FROM terms")
            connection.executemany(
                """
                INSERT INTO terms(
                    id, term, term_normalized, heading, definition,
                    redirect_to, letter, search_blob, quality_flags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        entry.id,
                        entry.term,
                        entry.term_normalized,
                        entry.heading,
                        entry.definition,
                        entry.redirect_to,
                        entry.letter,
                        entry.search_blob,
                        _quality_flags_json(entry.quality_flags),
                    )
                    for entry in payload.entries
                ),
            )
            connection.executemany(
                "INSERT INTO term_aliases(term_id, alias_normalized) VALUES (?, ?)",
                (
                    (entry.id, alias)
                    for entry in payload.entries
                    for alias in entry.aliases
                ),
            )
            report = _verify_import(
                connection,
                expected_terms=len(payload.entries),
                expected_aliases=expected_aliases,
            )
    except sqlite3.Error as exc:
        raise DictionaryImportError("SQLite rejected the dictionary import") from exc
    return report


def import_dictionary_file(
    input_path: str | Path,
    database_path: str | Path,
) -> ImportReport:
    """Validate JSON first, then migrate and atomically import it."""

    payload = load_dictionary_json(input_path)
    check_sqlite_fts5_trigram()
    with database_connection(database_path) as connection:
        apply_migrations(connection)
        return import_dictionary_payload(connection, payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg-psyco-import",
        description="Import the psychological dictionary JSON into SQLite",
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"dictionary JSON path (default: {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        report = import_dictionary_file(arguments.input, arguments.database)
    except (DictionaryImportError, MigrationError, SqliteCapabilityError) as exc:
        parser.error(str(exc))
    print(
        f"Imported {report.term_count} terms, {report.alias_count} aliases, "
        f"and {report.fts_count} FTS documents into {arguments.database}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
