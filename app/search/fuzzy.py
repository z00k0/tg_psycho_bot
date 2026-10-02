"""In-memory typo-tolerant matching for the final search fallback."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from rapidfuzz import fuzz, process

from app.search.models import FuzzyChoice, FuzzySuggestion

if TYPE_CHECKING:
    from app.db.repository import DictionaryRepository

MAX_FUZZY_SUGGESTIONS = 3


class FuzzyMatcher:
    """Match normalized input against a snapshot of terms and aliases."""

    def __init__(self, choices: Iterable[FuzzyChoice]) -> None:
        self._choices = tuple(choices)
        self._normalized_choices = tuple(choice.normalized for choice in self._choices)

    @classmethod
    def from_repository(cls, repository: DictionaryRepository) -> FuzzyMatcher:
        """Load the SQLite choices once while constructing the matcher."""

        return cls(repository.load_fuzzy_choices())

    @property
    def choices(self) -> tuple[FuzzyChoice, ...]:
        """Expose the immutable index snapshot for diagnostics."""

        return self._choices

    def suggest(self, normalized_query: str) -> tuple[FuzzySuggestion, ...]:
        """Return at most three unique articles ordered by fuzzy similarity."""

        if not self._choices:
            return ()

        # Extract every variant before deduplication. Limiting RapidFuzz to three
        # here could let aliases of one article displace other useful articles.
        matches = process.extract(
            normalized_query,
            self._normalized_choices,
            scorer=fuzz.WRatio,
            limit=None,
        )
        best_by_article: dict[int, FuzzySuggestion] = {}
        for _, score, choice_index in matches:
            choice = self._choices[choice_index]
            current = best_by_article.get(choice.article_id)
            if current is None or score > current.score:
                best_by_article[choice.article_id] = FuzzySuggestion(
                    article_id=choice.article_id,
                    term=choice.term,
                    score=float(score),
                )

        ordered = sorted(
            best_by_article.values(),
            key=lambda suggestion: (
                -suggestion.score,
                suggestion.term.casefold(),
                suggestion.article_id,
            ),
        )
        return tuple(ordered[:MAX_FUZZY_SUGGESTIONS])
