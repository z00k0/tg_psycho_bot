from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from app.db.connection import open_database, transaction
from app.db.migrate import apply_migrations
from app.db.repository import DictionaryRepository
from app.search.fts_query import FtsQueryError, build_fts_query
from app.search.normalize import normalize_query


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    database = open_database(":memory:")
    apply_migrations(database)
    with transaction(database):
        database.executemany(
            """
            INSERT INTO terms(
                id, term, term_normalized, heading, definition,
                redirect_to, letter, search_blob, quality_flags_json
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, '[]')
            """,
            [
                (
                    1,
                    "ПСИХОЛОГИЯ",
                    "психология",
                    "ПСИХОЛОГИЯ",
                    "Наука о психике и закономерностях её развития.",
                    "П",
                    "психология наука о душе",
                ),
                (
                    2,
                    "ТЕОРИЯ ЛИЧНОСТИ",
                    "теория личности",
                    "ТЕОРИЯ ЛИЧНОСТИ",
                    "Система представлений о структуре личности.",
                    "Т",
                    "теория личности персонология",
                ),
                (
                    3,
                    "ПАМЯТЬ",
                    "память",
                    "ПАМЯТЬ",
                    "Способность сохранять и воспроизводить опыт.",
                    "П",
                    "память запоминание",
                ),
                (
                    4,
                    "ДРУГОЕ",
                    "другое",
                    "ДРУГОЕ",
                    "Память рассматривается здесь только внутри определения.",
                    "Д",
                    "другое",
                ),
                (
                    5,
                    "АААА",
                    "аааа",
                    "АААА",
                    "Одинаковый общий маркер.",
                    "А",
                    "аааа",
                ),
                (
                    6,
                    "ББББ",
                    "бббб",
                    "ББББ",
                    "Одинаковый общий маркер.",
                    "Б",
                    "бббб",
                ),
                (
                    7,
                    "ВВВВ",
                    "вввв",
                    "ВВВВ",
                    "Одинаковый общий маркер.",
                    "В",
                    "вввв",
                ),
                (
                    8,
                    "СЛОВО OR ДРУГОЕ",
                    "слово or другое",
                    "СЛОВО OR ДРУГОЕ",
                    "Статья для проверки литерального поиска.",
                    "С",
                    "слово or другое",
                ),
                (
                    9,
                    "ЁЖИК",
                    "ежик",
                    "ЁЖИК",
                    "Небольшое животное с иголками.",
                    "Ё",
                    "ежик",
                ),
            ],
        )
    yield database
    database.close()


@pytest.fixture
def repository(connection: sqlite3.Connection) -> DictionaryRepository:
    return DictionaryRepository(connection)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("психология", '"психология"'),
        ('слово "в кавычках"', '"слово ""в кавычках"""'),
        ("слово OR другое", '"слово OR другое"'),
        ("NOT (слово*)", '"NOT (слово*)"'),
        ("слово-связка", '"слово-связка"'),
    ],
)
def test_build_fts_query_quotes_literal_text(value: str, expected: str) -> None:
    assert build_fts_query(value) == expected


@pytest.mark.parametrize("value", ["", None, 123])
def test_build_fts_query_rejects_invalid_values(value: object) -> None:
    with pytest.raises(FtsQueryError):
        build_fts_query(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("query", ["псих", "холог", "логия"])
def test_trigram_finds_substring_at_any_term_position(
    repository: DictionaryRepository,
    query: str,
) -> None:
    results = repository.search_fts(query, limit=5)

    assert results
    assert results[0].id == 1


@pytest.mark.parametrize("query", ["ПСИХ", "псих", "Псих"])
def test_normalized_case_variants_find_same_term(
    repository: DictionaryRepository,
    query: str,
) -> None:
    results = repository.search_fts(normalize_query(query), limit=5)

    assert results
    assert results[0].id == 1


def test_normalized_yo_variant_finds_term(
    repository: DictionaryRepository,
) -> None:
    results = repository.search_fts(normalize_query("ЁЖИ"), limit=5)

    assert results
    assert results[0].id == 9


def test_multiple_words_are_searched_as_one_literal_phrase(
    repository: DictionaryRepository,
) -> None:
    results = repository.search_fts("теория личности", limit=5)

    assert results
    assert results[0].id == 2


def test_alias_in_search_blob_is_searchable(repository: DictionaryRepository) -> None:
    results = repository.search_fts("персонолог", limit=5)

    assert results
    assert results[0].id == 2


def test_fts_operators_are_treated_as_literal_text(
    repository: DictionaryRepository,
) -> None:
    results = repository.search_fts("слово OR другое", limit=5)

    assert results
    assert results[0].id == 8


@pytest.mark.parametrize(
    "query",
    ['кавычка "', "звезда*", "OR", "NOT", "(скобки)", "слово-связка"],
)
def test_special_syntax_never_causes_an_fts_error(
    repository: DictionaryRepository,
    query: str,
) -> None:
    repository.search_fts(query, limit=5)


def test_query_shorter_than_trigram_does_not_access_fts(
    connection: sqlite3.Connection,
    repository: DictionaryRepository,
) -> None:
    statements: list[str] = []
    connection.set_trace_callback(statements.append)

    results = repository.search_fts("еж", limit=5)

    connection.set_trace_callback(None)
    assert results == []
    assert not any("terms_fts" in statement for statement in statements)


def test_term_match_ranks_above_definition_only_match(
    repository: DictionaryRepository,
) -> None:
    results = repository.search_fts("память", limit=5)

    assert [article.id for article in results[:2]] == [3, 4]


def test_limit_and_deterministic_tie_order(repository: DictionaryRepository) -> None:
    results = repository.search_fts("общий маркер", limit=2)

    assert [article.id for article in results] == [5, 6]


def test_unknown_substring_returns_empty_list(
    repository: DictionaryRepository,
) -> None:
    assert repository.search_fts("несуществующая строка", limit=5) == []


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_limit_must_be_a_positive_integer(
    repository: DictionaryRepository,
    limit: object,
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        repository.search_fts("псих", limit=limit)  # type: ignore[arg-type]
