from __future__ import annotations

from pathlib import Path

from app.db.connection import database_connection
from app.db.import_dictionary import import_dictionary_file
from app.db.repository import DictionaryRepository
from app.search.fuzzy import FuzzyMatcher
from app.search.models import ExactMatch, FtsMatches, SearchStrategy, Suggestions
from app.search.service import SearchService


def _real_service(database_path: Path) -> tuple[object, SearchService]:
    context = database_connection(database_path)
    connection = context.__enter__()
    repository = DictionaryRepository(connection)
    service = SearchService(
        repository,
        FuzzyMatcher.from_repository(repository),
        result_limit=5,
    )
    return context, service


def test_real_dictionary_exact_normalization_fts_and_fuzzy(
    workspace_tmp_path: Path,
) -> None:
    source = Path(__file__).parents[2] / "psychological_dictionary.json"
    database_path = workspace_tmp_path / "search.sqlite3"
    import_dictionary_file(source, database_path)
    context, service = _real_service(database_path)
    try:
        exact = service.search("  аБсТрАкЦиЯ!!! ")
        yo_variant = service.search("ВНИМАНИЯ ОБЪЕМ")
        substring = service.search("стракц")
        typo = service.search("абстракцыя")
    finally:
        context.__exit__(None, None, None)  # type: ignore[attr-defined]

    assert isinstance(exact, ExactMatch)
    assert exact.article.term == "АБСТРАКЦИЯ"
    assert exact.diagnostics.strategy is SearchStrategy.EXACT
    assert isinstance(yo_variant, ExactMatch)
    assert yo_variant.article.term == "ВНИМАНИЯ ОБЪЕМ"
    assert isinstance(substring, FtsMatches)
    assert substring.articles[0].term == "АБСТРАКЦИЯ"
    assert substring.diagnostics.strategy is SearchStrategy.FTS
    assert isinstance(typo, Suggestions)
    assert 1 <= len(typo.suggestions) <= 3
    assert typo.suggestions[0].term == "АБСТРАКЦИЯ"
    assert typo.diagnostics.strategy is SearchStrategy.FUZZY
