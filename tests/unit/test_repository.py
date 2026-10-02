from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.db.connection import open_database, transaction
from app.db.migrate import apply_migrations
from app.db.repository import DictionaryRepository
from app.search.models import DictionaryArticle
from app.search.normalize import normalize_query


@pytest.fixture
def repository() -> Iterator[DictionaryRepository]:
    connection = open_database(":memory:")
    apply_migrations(connection)
    with transaction(connection):
        connection.executemany(
            """
            INSERT INTO terms(
                id, term, term_normalized, heading, definition,
                redirect_to, letter, search_blob, quality_flags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "АБСТРАКЦИЯ",
                    "абстракция",
                    "АБСТРАКЦИЯ (от лат. abstractio)",
                    "Мысленное отвлечение от свойств предмета.",
                    None,
                    "А",
                    "абстракция отвлечение",
                    '["checked"]',
                ),
                (
                    2,
                    "МЫШЛЕНИЕ",
                    "мышление",
                    "МЫШЛЕНИЕ",
                    "Процесс познавательной деятельности.",
                    None,
                    "М",
                    "мышление размышление абстракция",
                    "[]",
                ),
                (
                    3,
                    "ЁЖ",
                    "еж",
                    "ЁЖ",
                    "Тестовая статья для проверки нормализации.",
                    "Животное",
                    "Ё",
                    "еж колючий еж",
                    "[]",
                ),
            ],
        )
        connection.executemany(
            "INSERT INTO term_aliases(term_id, alias_normalized) VALUES (?, ?)",
            [
                (1, "отвлечение"),
                (2, "размышление"),
                (2, "абстракция"),
                (3, "колючий еж"),
            ],
        )
    yield DictionaryRepository(connection)
    connection.close()


def test_get_existing_article_by_id(repository: DictionaryRepository) -> None:
    article = repository.get_by_id(1)

    assert article == DictionaryArticle(
        id=1,
        term="АБСТРАКЦИЯ",
        term_normalized="абстракция",
        heading="АБСТРАКЦИЯ (от лат. abstractio)",
        definition="Мысленное отвлечение от свойств предмета.",
        redirect_to=None,
        letter="А",
        quality_flags=("checked",),
    )


def test_get_unknown_article_by_id_returns_none(
    repository: DictionaryRepository,
) -> None:
    assert repository.get_by_id(999_999) is None


def test_exact_primary_term_has_priority_over_same_alias(
    repository: DictionaryRepository,
) -> None:
    article = repository.find_exact("абстракция")

    assert article is not None
    assert article.id == 1


def test_exact_alias_returns_owning_article(repository: DictionaryRepository) -> None:
    article = repository.find_exact("размышление")

    assert article is not None
    assert article.id == 2
    assert article.term == "МЫШЛЕНИЕ"


@pytest.mark.parametrize(
    "query",
    ["ЁЖ", "еж", "  ЁЖ  ", "...ёж!!!"],
)
def test_normalized_query_variants_find_same_article(
    repository: DictionaryRepository,
    query: str,
) -> None:
    article = repository.find_exact(normalize_query(query))

    assert article is not None
    assert article.id == 3


def test_normalized_alias_with_punctuation_finds_article(
    repository: DictionaryRepository,
) -> None:
    article = repository.find_exact(normalize_query("  КОЛЮЧИЙ—ЁЖ! "))

    assert article is not None
    assert article.id == 3


def test_unknown_term_returns_none(repository: DictionaryRepository) -> None:
    assert repository.find_exact("неизвестный термин") is None


def test_sql_like_input_is_data_and_does_not_change_database(
    repository: DictionaryRepository,
) -> None:
    attack = "' OR 1=1; DROP TABLE terms; --"

    assert repository.find_exact(attack) is None
    assert repository.get_by_id(1) is not None


def test_get_by_id_uses_a_bound_parameter(repository: DictionaryRepository) -> None:
    assert repository.get_by_id("1 OR 1=1") is None  # type: ignore[arg-type]
