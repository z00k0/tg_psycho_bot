from __future__ import annotations

from dataclasses import asdict

import pytest

from app.search.models import (
    DictionaryArticle,
    ExactMatch,
    FtsMatches,
    FuzzySuggestion,
    InvalidQuery,
    InvalidQueryReason,
    SearchStrategy,
    Suggestions,
)
from app.search.service import SearchService, SearchServiceError


def article(article_id: int, term: str) -> DictionaryArticle:
    return DictionaryArticle(
        id=article_id,
        term=term,
        term_normalized=term.casefold().replace("ё", "е"),
        heading=term,
        definition=f"Определение: {term}",
        redirect_to=None,
        letter=term[0],
        quality_flags=(),
    )


class SpyRepository:
    def __init__(
        self,
        *,
        exact: DictionaryArticle | None = None,
        fts: list[DictionaryArticle] | None = None,
        error_at: str | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self.exact = exact
        self.fts = [] if fts is None else fts
        self.error_at = error_at
        self.calls = [] if calls is None else calls
        self.fts_arguments: tuple[str, int] | None = None

    def find_exact(self, normalized_query: str) -> DictionaryArticle | None:
        self.calls.append(f"exact:{normalized_query}")
        if self.error_at == "exact":
            raise RuntimeError("database unavailable")
        return self.exact

    def search_fts(
        self,
        normalized_query: str,
        *,
        limit: int,
    ) -> list[DictionaryArticle]:
        self.calls.append(f"fts:{normalized_query}")
        self.fts_arguments = (normalized_query, limit)
        if self.error_at == "fts":
            raise RuntimeError("FTS unavailable")
        return self.fts


class SpyMatcher:
    def __init__(
        self,
        suggestions: tuple[FuzzySuggestion, ...] = (),
        *,
        fail: bool = False,
        calls: list[str] | None = None,
    ) -> None:
        self.suggestions = suggestions
        self.fail = fail
        self.calls = [] if calls is None else calls

    def suggest(self, normalized_query: str) -> tuple[FuzzySuggestion, ...]:
        self.calls.append(f"fuzzy:{normalized_query}")
        if self.fail:
            raise RuntimeError("matcher unavailable")
        return self.suggestions


def test_exact_match_stops_before_fts_and_fuzzy() -> None:
    calls: list[str] = []
    expected = article(1, "ЁЖИК")
    repository = SpyRepository(exact=expected, calls=calls)
    matcher = SpyMatcher(calls=calls)
    service = SearchService(repository, matcher, result_limit=5)

    result = service.search("  ЁЖИК!!! ")

    assert isinstance(result, ExactMatch)
    assert result.article == expected
    assert result.diagnostics.strategy is SearchStrategy.EXACT
    assert result.diagnostics.normalized_length == 4
    assert result.diagnostics.result_count == 1
    assert calls == ["exact:ежик"]


def test_fts_match_stops_before_fuzzy_and_uses_configured_limit() -> None:
    calls: list[str] = []
    matches = [article(2, "ПСИХОЛОГИЯ"), article(3, "ПСИХОЛОГИЯ ТРУДА")]
    repository = SpyRepository(fts=matches, calls=calls)
    matcher = SpyMatcher(calls=calls)
    service = SearchService(repository, matcher, result_limit=2)

    result = service.search("ПСИХОЛОГ")

    assert isinstance(result, FtsMatches)
    assert result.articles == tuple(matches)
    assert result.diagnostics.strategy is SearchStrategy.FTS
    assert result.diagnostics.result_count == 2
    assert repository.fts_arguments == ("психолог", 2)
    assert calls == ["exact:психолог", "fts:психолог"]


def test_fuzzy_runs_only_after_empty_exact_and_fts() -> None:
    calls: list[str] = []
    suggestions = (
        FuzzySuggestion(article_id=1, term="АБСТРАКЦИЯ", score=95.0),
        FuzzySuggestion(article_id=2, term="АДАПТАЦИЯ", score=70.0),
    )
    repository = SpyRepository(calls=calls)
    matcher = SpyMatcher(suggestions, calls=calls)
    service = SearchService(repository, matcher, result_limit=5)

    result = service.search("АБСТРАКЦЫЯ")

    assert isinstance(result, Suggestions)
    assert result.suggestions == suggestions
    assert result.diagnostics.strategy is SearchStrategy.FUZZY
    assert result.diagnostics.result_count == 2
    assert calls == [
        "exact:абстракцыя",
        "fts:абстракцыя",
        "fuzzy:абстракцыя",
    ]


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("", InvalidQueryReason.EMPTY),
        ("!!!", InvalidQueryReason.EMPTY),
        (123, InvalidQueryReason.INVALID),
    ],
)
def test_invalid_query_does_not_call_repository_or_matcher(
    query: object,
    reason: InvalidQueryReason,
) -> None:
    calls: list[str] = []
    service = SearchService(
        SpyRepository(calls=calls),
        SpyMatcher(calls=calls),
        result_limit=5,
    )

    result = service.search(query)  # type: ignore[arg-type]

    assert isinstance(result, InvalidQuery)
    assert result.reason is reason
    assert result.diagnostics.strategy is SearchStrategy.INVALID
    assert result.diagnostics.normalized_length is None
    assert calls == []


def test_too_long_query_is_invalid_before_repository_access() -> None:
    calls: list[str] = []
    service = SearchService(
        SpyRepository(calls=calls),
        SpyMatcher(calls=calls),
        result_limit=5,
        max_query_length=4,
    )

    result = service.search("шесть")

    assert isinstance(result, InvalidQuery)
    assert result.reason is InvalidQueryReason.TOO_LONG
    assert calls == []


def test_short_query_skips_fts_but_runs_exact_then_fuzzy() -> None:
    calls: list[str] = []
    suggestion = FuzzySuggestion(article_id=1, term="ЁЖ", score=100.0)
    service = SearchService(
        SpyRepository(calls=calls),
        SpyMatcher((suggestion,), calls=calls),
        result_limit=5,
    )

    result = service.search("ЁЖ")

    assert isinstance(result, Suggestions)
    assert result.suggestions == (suggestion,)
    assert calls == ["exact:еж", "fuzzy:еж"]


def test_empty_fuzzy_result_is_still_one_suggestions_result() -> None:
    service = SearchService(SpyRepository(), SpyMatcher(), result_limit=5)

    result = service.search("неизвестный")

    assert isinstance(result, Suggestions)
    assert result.suggestions == ()
    assert result.diagnostics.result_count == 0


@pytest.mark.parametrize(
    ("error_at", "expected_strategy", "expected_calls"),
    [
        ("exact", SearchStrategy.EXACT, ["exact:запрос"]),
        ("fts", SearchStrategy.FTS, ["exact:запрос", "fts:запрос"]),
    ],
)
def test_repository_failure_becomes_controlled_internal_error(
    error_at: str,
    expected_strategy: SearchStrategy,
    expected_calls: list[str],
) -> None:
    calls: list[str] = []
    service = SearchService(
        SpyRepository(error_at=error_at, calls=calls),
        SpyMatcher(calls=calls),
        result_limit=5,
    )

    with pytest.raises(SearchServiceError) as captured:
        service.search("ЗАПРОС")

    assert captured.value.strategy is expected_strategy
    assert isinstance(captured.value.__cause__, RuntimeError)
    assert calls == expected_calls


def test_fuzzy_failure_becomes_controlled_internal_error() -> None:
    calls: list[str] = []
    service = SearchService(
        SpyRepository(calls=calls),
        SpyMatcher(fail=True, calls=calls),
        result_limit=5,
    )

    with pytest.raises(SearchServiceError) as captured:
        service.search("ЗАПРОС")

    assert captured.value.strategy is SearchStrategy.FUZZY
    assert calls == ["exact:запрос", "fts:запрос", "fuzzy:запрос"]


def test_diagnostics_do_not_retain_full_user_query() -> None:
    raw_query = "СЕКРЕТНЫЙ ПОЛЬЗОВАТЕЛЬСКИЙ ТЕКСТ"
    result = SearchService(SpyRepository(), SpyMatcher(), result_limit=5).search(raw_query)

    assert isinstance(result, Suggestions)
    assert raw_query.casefold() not in repr(asdict(result.diagnostics)).casefold()
    assert result.diagnostics.normalized_length == len(raw_query.casefold())


@pytest.mark.parametrize(
    ("result_limit", "max_query_length"),
    [(0, 200), (True, 200), (1.5, 200), (5, 0), (5, True), (5, 1.5)],
)
def test_service_limits_must_be_positive_integers(
    result_limit: object,
    max_query_length: object,
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        SearchService(
            SpyRepository(),
            SpyMatcher(),
            result_limit=result_limit,  # type: ignore[arg-type]
            max_query_length=max_query_length,  # type: ignore[arg-type]
        )
