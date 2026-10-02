from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from app.db.connection import open_database, transaction
from app.db.migrate import apply_migrations
from app.db.repository import DictionaryRepository
from app.search.fuzzy import FuzzyMatcher
from app.search.models import FuzzyChoice
from app.search.normalize import normalize_query


def choice(article_id: int, term: str, normalized: str | None = None) -> FuzzyChoice:
    return FuzzyChoice(
        article_id=article_id,
        term=term,
        normalized=normalized or normalize_query(term),
    )


@pytest.fixture
def dictionary_choices() -> tuple[FuzzyChoice, ...]:
    return (
        choice(1, "АБСТРАКЦИЯ"),
        choice(2, "АДАПТАЦИЯ"),
        choice(3, "АГРЕССИЯ"),
        choice(4, "МЫШЛЕНИЕ"),
        choice(5, "ВОСПРИЯТИЕ"),
    )


@pytest.mark.parametrize(
    "misspelled",
    [
        "абстракцыя",
        "абстрация",
        "абстраккция",
        "абстаркция",
    ],
)
def test_russian_typo_returns_expected_term_first(
    dictionary_choices: tuple[FuzzyChoice, ...],
    misspelled: str,
) -> None:
    matcher = FuzzyMatcher(dictionary_choices)

    suggestions = matcher.suggest(normalize_query(misspelled))

    assert suggestions[0].article_id == 1
    assert suggestions[0].term == "АБСТРАКЦИЯ"


def test_case_and_yo_variants_are_matched_after_normalization() -> None:
    matcher = FuzzyMatcher(
        (
            choice(1, "ЁЖИК"),
            choice(2, "ЕРШИК"),
            choice(3, "ЕЖЕВИКА"),
        )
    )

    suggestions = matcher.suggest(normalize_query("ёЖыК"))

    assert suggestions[0].article_id == 1


def test_returns_exactly_three_unique_articles_when_available(
    dictionary_choices: tuple[FuzzyChoice, ...],
) -> None:
    suggestions = FuzzyMatcher(dictionary_choices).suggest("абстракцыя")

    assert len(suggestions) == 3
    assert len({suggestion.article_id for suggestion in suggestions}) == 3


@pytest.mark.parametrize("size", [1, 2])
def test_small_dictionary_returns_every_available_article(size: int) -> None:
    choices = tuple(choice(index, f"ТЕРМИН {index}") for index in range(1, size + 1))

    suggestions = FuzzyMatcher(choices).suggest("термин")

    assert len(suggestions) == size


def test_primary_term_and_alias_are_deduplicated_by_article_id() -> None:
    matcher = FuzzyMatcher(
        (
            choice(1, "АБСТРАКЦИЯ"),
            choice(1, "АБСТРАКЦИЯ", "отвлечение"),
            choice(2, "ВНИМАНИЕ"),
            choice(3, "ПАМЯТЬ"),
            choice(4, "МЫШЛЕНИЕ"),
        )
    )

    suggestions = matcher.suggest("отвлечение")

    assert suggestions[0].article_id == 1
    assert [item.article_id for item in suggestions].count(1) == 1
    assert len(suggestions) == 3


def test_empty_choices_return_empty_tuple() -> None:
    assert FuzzyMatcher(()).suggest("что угодно") == ()


def test_equal_scores_are_sorted_by_term_then_id() -> None:
    matcher = FuzzyMatcher(
        (
            choice(3, "ЯБЛОКО", "общий"),
            choice(2, "АРБУЗ", "общий"),
            choice(1, "АРБУЗ", "общий"),
        )
    )

    suggestions = matcher.suggest("общий")

    assert [item.article_id for item in suggestions] == [1, 2, 3]


def test_suggestion_score_is_available_for_diagnostics() -> None:
    suggestion = FuzzyMatcher((choice(1, "ПАМЯТЬ"),)).suggest("памят")[0]

    assert suggestion.term == "ПАМЯТЬ"
    assert 0.0 < suggestion.score <= 100.0


def test_input_collection_is_copied_to_immutable_snapshot() -> None:
    source = [choice(1, "ПАМЯТЬ")]
    matcher = FuzzyMatcher(source)

    source.append(choice(2, "МЫШЛЕНИЕ"))

    assert isinstance(matcher.choices, tuple)
    assert [item.article_id for item in matcher.choices] == [1]


@pytest.fixture
def repository_connection() -> Iterator[sqlite3.Connection]:
    connection = open_database(":memory:")
    apply_migrations(connection)
    with transaction(connection):
        connection.executemany(
            """
            INSERT INTO terms(
                id, term, term_normalized, heading, definition,
                redirect_to, letter, search_blob, quality_flags_json
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, '[]')
            """,
            [
                (2, "МЫШЛЕНИЕ", "мышление", "МЫШЛЕНИЕ", "Определение", "М", "мышление"),
                (
                    1,
                    "АБСТРАКЦИЯ",
                    "абстракция",
                    "АБСТРАКЦИЯ",
                    "Определение",
                    "А",
                    "абстракция отвлечение",
                ),
            ],
        )
        connection.executemany(
            "INSERT INTO term_aliases(term_id, alias_normalized) VALUES (?, ?)",
            [(1, "отвлечение"), (1, "абстрагирование"), (2, "размышление")],
        )
    yield connection
    connection.close()


def test_repository_loads_primary_terms_and_aliases_in_stable_order(
    repository_connection: sqlite3.Connection,
) -> None:
    choices = DictionaryRepository(repository_connection).load_fuzzy_choices()

    assert choices == (
        choice(1, "АБСТРАКЦИЯ"),
        choice(1, "АБСТРАКЦИЯ", "абстрагирование"),
        choice(1, "АБСТРАКЦИЯ", "отвлечение"),
        choice(2, "МЫШЛЕНИЕ"),
        choice(2, "МЫШЛЕНИЕ", "размышление"),
    )


def test_matcher_loaded_from_repository_does_not_query_database_per_message(
    repository_connection: sqlite3.Connection,
) -> None:
    matcher = FuzzyMatcher.from_repository(DictionaryRepository(repository_connection))
    statements: list[str] = []
    repository_connection.set_trace_callback(statements.append)

    first = matcher.suggest("абстракцыя")
    second = matcher.suggest("размышленее")

    repository_connection.set_trace_callback(None)
    assert first[0].article_id == 1
    assert second[0].article_id == 2
    assert statements == []
