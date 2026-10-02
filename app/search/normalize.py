"""Canonical normalization shared by every dictionary search strategy."""

from __future__ import annotations

import unicodedata

DEFAULT_MAX_QUERY_LENGTH = 200


class QueryNormalizationError(ValueError):
    """Base class for controlled user-query validation errors."""


class InvalidQueryError(QueryNormalizationError):
    """Raised when a query is not a string or configuration is invalid."""


class EmptyQueryError(QueryNormalizationError):
    """Raised when no searchable characters remain after normalization."""


class QueryTooLongError(QueryNormalizationError):
    """Raised when a normalized query exceeds the configured limit."""


def normalize_query(
    value: str,
    *,
    max_length: int = DEFAULT_MAX_QUERY_LENGTH,
) -> str:
    """Return a lowercase, punctuation-insensitive Russian search string.

    Unicode is composed to NFC, ``ё`` is folded to ``е``, letters and digits
    are retained, and every other run is represented by one ASCII space.
    """

    if not isinstance(value, str):
        raise InvalidQueryError("Search query must be a string")
    if not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 1:
        raise InvalidQueryError("max_length must be a positive integer")

    value = unicodedata.normalize("NFC", value).casefold().replace("ё", "е")
    normalized = "".join(character if character.isalnum() else " " for character in value)
    normalized = " ".join(normalized.split())

    if not normalized:
        raise EmptyQueryError("Search query is empty after normalization")
    if len(normalized) > max_length:
        raise QueryTooLongError(
            f"Search query exceeds the maximum length of {max_length} characters"
        )
    return normalized
