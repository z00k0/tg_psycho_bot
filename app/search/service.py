"""Single ordered search pipeline shared by Telegram handlers."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Protocol

from app.search.models import (
    DictionaryArticle,
    ExactMatch,
    FtsMatches,
    FuzzySuggestion,
    InvalidQuery,
    InvalidQueryReason,
    SearchDiagnostics,
    SearchResult,
    SearchStrategy,
    Suggestions,
)
from app.search.normalize import (
    DEFAULT_MAX_QUERY_LENGTH,
    EmptyQueryError,
    QueryNormalizationError,
    QueryTooLongError,
    normalize_query,
)

logger = logging.getLogger("tg_psyco.search")


class SearchRepository(Protocol):
    """Repository operations required by the search pipeline."""

    def find_exact(self, normalized_query: str) -> DictionaryArticle | None: ...

    def search_fts(
        self,
        normalized_query: str,
        *,
        limit: int,
    ) -> list[DictionaryArticle]: ...


class SuggestionMatcher(Protocol):
    """In-memory fuzzy operation required by the search pipeline."""

    def suggest(self, normalized_query: str) -> tuple[FuzzySuggestion, ...]: ...


class SearchServiceError(RuntimeError):
    """Controlled internal failure preserving the responsible pipeline stage."""

    def __init__(self, strategy: SearchStrategy) -> None:
        self.strategy = strategy
        super().__init__(f"Dictionary search failed during {strategy.value} strategy")


def _diagnostics(
    strategy: SearchStrategy,
    normalized_query: str | None,
    result_count: int,
) -> SearchDiagnostics:
    return SearchDiagnostics(
        strategy=strategy,
        normalized_length=(len(normalized_query) if normalized_query is not None else None),
        result_count=result_count,
    )


def _invalid_reason(error: QueryNormalizationError) -> InvalidQueryReason:
    if isinstance(error, EmptyQueryError):
        return InvalidQueryReason.EMPTY
    if isinstance(error, QueryTooLongError):
        return InvalidQueryReason.TOO_LONG
    return InvalidQueryReason.INVALID


class SearchService:
    """Run normalize → exact → FTS → fuzzy with early termination."""

    def __init__(
        self,
        repository: SearchRepository,
        fuzzy_matcher: SuggestionMatcher,
        *,
        result_limit: int,
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
    ) -> None:
        if (
            not isinstance(result_limit, int)
            or isinstance(result_limit, bool)
            or result_limit < 1
        ):
            raise ValueError("result_limit must be a positive integer")
        if (
            not isinstance(max_query_length, int)
            or isinstance(max_query_length, bool)
            or max_query_length < 1
        ):
            raise ValueError("max_query_length must be a positive integer")
        self._repository = repository
        self._fuzzy_matcher = fuzzy_matcher
        self._result_limit = result_limit
        self._max_query_length = max_query_length

    def search(self, query: str) -> SearchResult:
        """Return exactly one typed result without retaining the source query."""

        started_at = perf_counter()
        try:
            normalized = normalize_query(query, max_length=self._max_query_length)
        except QueryNormalizationError as exc:
            result = InvalidQuery(
                reason=_invalid_reason(exc),
                message=str(exc),
                diagnostics=_diagnostics(SearchStrategy.INVALID, None, 0),
            )
            self._log_completed(result, started_at)
            return result

        try:
            exact = self._repository.find_exact(normalized)
        except Exception as exc:
            self._log_failed(SearchStrategy.EXACT, started_at, exc)
            raise SearchServiceError(SearchStrategy.EXACT) from exc
        if exact is not None:
            result = ExactMatch(
                article=exact,
                diagnostics=_diagnostics(SearchStrategy.EXACT, normalized, 1),
            )
            self._log_completed(result, started_at)
            return result

        if len(normalized) >= 3:
            try:
                fts_matches = self._repository.search_fts(
                    normalized,
                    limit=self._result_limit,
                )
            except Exception as exc:
                self._log_failed(SearchStrategy.FTS, started_at, exc)
                raise SearchServiceError(SearchStrategy.FTS) from exc
            if fts_matches:
                articles = tuple(fts_matches)
                result = FtsMatches(
                    articles=articles,
                    diagnostics=_diagnostics(
                        SearchStrategy.FTS,
                        normalized,
                        len(articles),
                    ),
                )
                self._log_completed(result, started_at)
                return result

        try:
            suggestions = tuple(self._fuzzy_matcher.suggest(normalized))
        except Exception as exc:
            self._log_failed(SearchStrategy.FUZZY, started_at, exc)
            raise SearchServiceError(SearchStrategy.FUZZY) from exc
        result = Suggestions(
            suggestions=suggestions,
            diagnostics=_diagnostics(
                SearchStrategy.FUZZY,
                normalized,
                len(suggestions),
            ),
        )
        self._log_completed(result, started_at)
        return result

    @staticmethod
    def _log_completed(result: SearchResult, started_at: float) -> None:
        diagnostics = result.diagnostics
        logger.info(
            "search_completed",
            extra={
                "event": "search_completed",
                "strategy": diagnostics.strategy.value,
                "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                "result_count": diagnostics.result_count,
                "normalized_length": diagnostics.normalized_length,
            },
        )

    @staticmethod
    def _log_failed(
        strategy: SearchStrategy,
        started_at: float,
        error: Exception,
    ) -> None:
        logger.error(
            "search_failed",
            extra={
                "event": "search_failed",
                "strategy": strategy.value,
                "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                "result_count": 0,
                "error_type": type(error).__name__,
            },
        )
