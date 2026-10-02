from __future__ import annotations

import unicodedata

import pytest

from app.search.normalize import (
    EmptyQueryError,
    InvalidQueryError,
    QueryTooLongError,
    normalize_query,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("  АБСТРАКЦИЯ  ", "абстракция"),
        ("Ёмкость ёлки ЕЖ", "емкость елки еж"),
        ("нервно-мышечная, релаксация", "нервно мышечная релаксация"),
        ("А, А.   (АНОНИМНЫЕ)", "а а анонимные"),
        ("Тест № 123", "тест 123"),
        ("строка\tс\nпробелами", "строка с пробелами"),
    ],
)
def test_normalizes_representative_queries(source: str, expected: str) -> None:
    assert normalize_query(source) == expected


def test_normalizes_nfc_and_nfd_equally() -> None:
    nfc = "ЙОД"
    nfd = unicodedata.normalize("NFD", nfc)

    assert normalize_query(nfc) == normalize_query(nfd) == "йод"


@pytest.mark.parametrize("source", ["", "   ", "...—()", "\x00\x1f\u200d"])
def test_rejects_empty_normalized_query(source: str) -> None:
    with pytest.raises(EmptyQueryError):
        normalize_query(source)


def test_accepts_query_at_length_limit() -> None:
    assert normalize_query("а" * 10, max_length=10) == "а" * 10


def test_rejects_query_above_length_limit() -> None:
    with pytest.raises(QueryTooLongError, match="10"):
        normalize_query("а" * 11, max_length=10)


@pytest.mark.parametrize("value", [None, 42, b"query"])
def test_rejects_non_string_query(value: object) -> None:
    with pytest.raises(InvalidQueryError):
        normalize_query(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("max_length", [0, -1, True, 1.5])
def test_rejects_invalid_max_length(max_length: object) -> None:
    with pytest.raises(InvalidQueryError):
        normalize_query("query", max_length=max_length)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "source",
    [
        "Абстракция",
        "ЁЖ",
        "нервно-мышечная релаксация",
        "  несколько   пробелов ",
        "тест 123",
    ],
)
def test_normalization_is_idempotent(source: str) -> None:
    normalized = normalize_query(source)
    assert normalize_query(normalized) == normalized
