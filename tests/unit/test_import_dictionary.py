from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.db.connection import database_connection
from app.db.import_dictionary import (
    DictionaryImportError,
    import_dictionary_file,
    import_dictionary_payload,
    load_dictionary_json,
    parse_dictionary_payload,
)
from app.db.migrate import apply_migrations
from app.main import main as app_main


def sample_entry(
    entry_id: int,
    term: str,
    *,
    search_terms: list[str] | None = None,
    redirect_to: str | None = None,
    quality_flags: list[str] | None = None,
) -> dict[str, object]:
    normalized = term.lower().replace("ё", "е").replace("-", " ")
    return {
        "id": entry_id,
        "term": term,
        "term_normalized": normalized,
        "search_terms": search_terms or [normalized],
        "letter": term[0],
        "heading": f"{term} (заголовок)",
        "definition": f"Определение для {term}",
        "redirect_to": redirect_to,
        "quality_flags": quality_flags or [],
    }


def sample_payload() -> dict[str, object]:
    entries = [
        sample_entry(
            1,
            "ЁЖ",
            search_terms=["ЕЖ", "КОЛЮЧИЙ ЁЖ", "ЛЕСНОЙ ЕЖ", "еж"],
            quality_flags=["short_heading"],
        ),
        sample_entry(2, "АБСТРАКЦИЯ"),
        sample_entry(
            3,
            "АБЕРРАЦИЯ ПОЛОВАЯ",
            redirect_to="Половые извращения",
        ),
    ]
    return {"schema_version": 1, "entry_count": len(entries), "entries": entries}


def write_payload(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_imports_minimal_dictionary_with_aliases_and_metadata(
    workspace_tmp_path: Path,
) -> None:
    json_path = workspace_tmp_path / "dictionary.json"
    database_path = workspace_tmp_path / "dictionary.sqlite3"
    write_payload(json_path, sample_payload())

    report = import_dictionary_file(json_path, database_path)

    assert report.term_count == report.fts_count == 3
    assert report.alias_count == 2
    with database_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT term, term_normalized, redirect_to, search_blob, quality_flags_json
            FROM terms WHERE id = 1
            """
        ).fetchone()
        assert row["term"] == "ЁЖ"
        assert row["term_normalized"] == "еж"
        assert row["redirect_to"] is None
        assert row["search_blob"] == "еж колючий еж лесной еж"
        assert json.loads(row["quality_flags_json"]) == ["short_heading"]
        aliases = connection.execute(
            "SELECT alias_normalized FROM term_aliases WHERE term_id = 1"
            " ORDER BY alias_normalized"
        ).fetchall()
        assert [row[0] for row in aliases] == ["колючий еж", "лесной еж"]
        assert connection.execute(
            "SELECT redirect_to FROM terms WHERE id = 3"
        ).fetchone()[0] == "Половые извращения"


def test_repeated_import_is_idempotent(workspace_tmp_path: Path) -> None:
    json_path = workspace_tmp_path / "dictionary.json"
    database_path = workspace_tmp_path / "dictionary.sqlite3"
    write_payload(json_path, sample_payload())

    first = import_dictionary_file(json_path, database_path)
    second = import_dictionary_file(json_path, database_path)

    assert second == first
    with database_connection(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM terms").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM term_aliases").fetchone()[0] == 2


def test_application_cli_import_command(
    workspace_tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    json_path = workspace_tmp_path / "dictionary.json"
    database_path = workspace_tmp_path / "dictionary.sqlite3"
    write_payload(json_path, sample_payload())

    result = app_main(
        ["import-dictionary", str(json_path), "--database", str(database_path)]
    )

    assert result == 0
    assert "Imported 3 terms, 2 aliases, and 3 FTS documents" in capsys.readouterr().out
    with database_connection(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM terms").fetchone()[0] == 3


def test_invalid_json_does_not_create_database(workspace_tmp_path: Path) -> None:
    json_path = workspace_tmp_path / "invalid.json"
    database_path = workspace_tmp_path / "dictionary.sqlite3"
    json_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(DictionaryImportError, match="not valid JSON"):
        import_dictionary_file(json_path, database_path)

    assert not database_path.exists()


@pytest.mark.parametrize("schema_version", [0, 2])
def test_rejects_unsupported_schema_version(schema_version: int) -> None:
    payload = sample_payload()
    payload["schema_version"] = schema_version

    with pytest.raises(DictionaryImportError, match="schema_version"):
        parse_dictionary_payload(payload)


def test_rejects_missing_required_entry_field() -> None:
    payload = sample_payload()
    del payload["entries"][1]["definition"]  # type: ignore[index]

    with pytest.raises(DictionaryImportError, match=r"entries\[1\]\.definition"):
        parse_dictionary_payload(payload)


def test_rejects_entry_count_mismatch() -> None:
    payload = sample_payload()
    payload["entry_count"] = 999

    with pytest.raises(DictionaryImportError, match="entry_count"):
        parse_dictionary_payload(payload)


def test_rejects_duplicate_id() -> None:
    payload = sample_payload()
    payload["entries"][1]["id"] = 1  # type: ignore[index]

    with pytest.raises(DictionaryImportError, match="Duplicate entry id"):
        parse_dictionary_payload(payload)


def test_rejects_duplicate_normalized_term() -> None:
    payload = sample_payload()
    duplicate = deepcopy(payload["entries"][0])  # type: ignore[index]
    duplicate["id"] = 99
    payload["entries"].append(duplicate)  # type: ignore[union-attr]
    payload["entry_count"] = 4

    with pytest.raises(DictionaryImportError, match="Duplicate normalized term"):
        parse_dictionary_payload(payload)


def test_rejects_mismatched_source_normalization() -> None:
    payload = sample_payload()
    payload["entries"][0]["term_normalized"] = "другое"  # type: ignore[index]

    with pytest.raises(DictionaryImportError, match="does not match"):
        parse_dictionary_payload(payload)


def test_database_error_rolls_back_to_previous_dictionary() -> None:
    original = parse_dictionary_payload(
        {
            "schema_version": 1,
            "entry_count": 1,
            "entries": [sample_entry(10, "СТАРЫЙ")],
        }
    )
    replacement = parse_dictionary_payload(sample_payload())
    with database_connection(":memory:") as connection:
        apply_migrations(connection)
        import_dictionary_payload(connection, original)
        connection.execute(
            """
            CREATE TRIGGER reject_second_term BEFORE INSERT ON terms
            WHEN new.id = 2
            BEGIN
                SELECT RAISE(ABORT, 'rejected by test');
            END
            """
        )

        with pytest.raises(DictionaryImportError, match="SQLite rejected"):
            import_dictionary_payload(connection, replacement)

        rows = connection.execute("SELECT id, term FROM terms").fetchall()
        assert [tuple(row) for row in rows] == [(10, "СТАРЫЙ")]
        assert connection.execute("SELECT COUNT(*) FROM terms_fts_docsize").fetchone()[0] == 1


def test_load_dictionary_json_accepts_utf8_bom(workspace_tmp_path: Path) -> None:
    json_path = workspace_tmp_path / "dictionary.json"
    encoded = json.dumps(sample_payload(), ensure_ascii=False).encode("utf-8-sig")
    json_path.write_bytes(encoded)

    payload = load_dictionary_json(json_path)

    assert len(payload.entries) == 3
