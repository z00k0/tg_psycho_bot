from __future__ import annotations

import json
from pathlib import Path

from app.db.connection import database_connection
from app.db.import_dictionary import import_dictionary_file


def test_imports_real_dictionary_into_sqlite(workspace_tmp_path: Path) -> None:
    project_root = Path(__file__).parents[2]
    source_path = project_root / "psychological_dictionary.json"
    database_path = workspace_tmp_path / "real_dictionary.sqlite3"
    source = json.loads(source_path.read_text(encoding="utf-8"))

    report = import_dictionary_file(source_path, database_path)

    assert report.term_count == report.fts_count == source["entry_count"] == 1978
    with database_connection(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM terms WHERE trim(definition) = ''"
        ).fetchone()[0] == 0
        imported = connection.execute(
            "SELECT id, term, definition FROM terms ORDER BY id"
        ).fetchall()
        expected = sorted(
            (
                entry["id"],
                entry["term"],
                entry["definition"],
            )
            for entry in source["entries"]
        )
        assert [tuple(row) for row in imported] == expected
