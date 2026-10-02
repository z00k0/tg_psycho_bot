"""Domain models returned by dictionary search components."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class DictionaryArticle:
    """A dictionary article independent from SQLite and Telegram types."""

    id: int
    term: str
    term_normalized: str
    heading: str
    definition: str
    redirect_to: str | None
    letter: str
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FuzzyChoice:
    """One normalized primary term or alias held in the fuzzy index."""

    article_id: int
    term: str
    normalized: str


@dataclass(frozen=True, slots=True)
class FuzzySuggestion:
    """One deduplicated fuzzy result with a diagnostic similarity score."""

    article_id: int
    term: str
    score: float


class SearchStrategy(StrEnum):
    """The terminal strategy selected by the search pipeline."""

    EXACT = "exact"
    FTS = "fts"
    FUZZY = "fuzzy"
    INVALID = "invalid"


class InvalidQueryReason(StrEnum):
    """Stable reason codes suitable for Telegram-facing error mapping."""

    EMPTY = "empty"
    TOO_LONG = "too_long"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class SearchDiagnostics:
    """Non-sensitive metadata about a completed search attempt."""

    strategy: SearchStrategy
    normalized_length: int | None
    result_count: int


@dataclass(frozen=True, slots=True)
class ExactMatch:
    article: DictionaryArticle
    diagnostics: SearchDiagnostics


@dataclass(frozen=True, slots=True)
class FtsMatches:
    articles: tuple[DictionaryArticle, ...]
    diagnostics: SearchDiagnostics


@dataclass(frozen=True, slots=True)
class Suggestions:
    suggestions: tuple[FuzzySuggestion, ...]
    diagnostics: SearchDiagnostics


@dataclass(frozen=True, slots=True)
class InvalidQuery:
    reason: InvalidQueryReason
    message: str
    diagnostics: SearchDiagnostics


type SearchResult = ExactMatch | FtsMatches | Suggestions | InvalidQuery
