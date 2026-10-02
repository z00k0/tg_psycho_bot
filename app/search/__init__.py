"""Dictionary search domain."""

from app.search.fts_query import FtsQueryError, build_fts_query
from app.search.fuzzy import MAX_FUZZY_SUGGESTIONS, FuzzyMatcher
from app.search.models import (
    DictionaryArticle,
    ExactMatch,
    FtsMatches,
    FuzzyChoice,
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
    InvalidQueryError,
    QueryNormalizationError,
    QueryTooLongError,
    normalize_query,
)
from app.search.service import SearchService, SearchServiceError

__all__ = [
    "DEFAULT_MAX_QUERY_LENGTH",
    "DictionaryArticle",
    "EmptyQueryError",
    "ExactMatch",
    "FtsQueryError",
    "FuzzyChoice",
    "FuzzyMatcher",
    "FuzzySuggestion",
    "FtsMatches",
    "InvalidQuery",
    "InvalidQueryReason",
    "InvalidQueryError",
    "MAX_FUZZY_SUGGESTIONS",
    "QueryNormalizationError",
    "QueryTooLongError",
    "SearchDiagnostics",
    "SearchResult",
    "SearchService",
    "SearchServiceError",
    "SearchStrategy",
    "Suggestions",
    "build_fts_query",
    "normalize_query",
]
