"""Safe construction of literal SQLite FTS5 queries."""

from __future__ import annotations


class FtsQueryError(ValueError):
    """Raised when an FTS query cannot represent searchable text."""


def build_fts_query(value: str) -> str:
    """Return one quoted FTS5 phrase without exposing query operators.

    Double quotes are escaped according to the FTS5 string grammar. The result
    is intended to be passed to ``MATCH`` as a bound SQL parameter.
    """

    if not isinstance(value, str):
        raise FtsQueryError("FTS query must be a string")
    if not value:
        raise FtsQueryError("FTS query must not be empty")
    escaped = value.replace('"', '""')
    return f'"{escaped}"'
