from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from app.logging_config import JsonLogFormatter, SecretRedactionFilter
from app.search.models import FuzzySuggestion, SearchStrategy
from app.search.service import SearchService
from tests.unit.test_search_service import SpyMatcher, SpyRepository, article


def _recorded_json(
    message: str,
    *args: object,
    secrets: tuple[str, ...] = (),
    exc_info: tuple[type[BaseException], BaseException, object] | None = None,
) -> dict[str, object]:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter(secrets))
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("test.safe-logging")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info(message, *args, exc_info=exc_info)
    return json.loads(stream.getvalue())


def test_secret_filter_redacts_message_arguments_and_omits_exception_text() -> None:
    token = "123456:test-token"
    secret = "webhook_secret-test"
    error = RuntimeError(f"failed with {token} and {secret}")

    payload = _recorded_json(
        "credentials: %s / %s",
        token,
        secret,
        secrets=(token, secret),
        exc_info=(RuntimeError, error, None),
    )
    serialized = json.dumps(payload, ensure_ascii=False)

    assert token not in serialized
    assert secret not in serialized
    assert serialized.count("<redacted>") == 2
    assert payload["error_type"] == "RuntimeError"
    assert "failed with" not in serialized


def test_search_logs_strategy_metrics_without_query(caplog: object) -> None:
    private_query = "СОВЕРШЕННО СЕКРЕТНЫЙ ЗАПРОС"
    service = SearchService(
        SpyRepository(exact=article(1, "РЕЗУЛЬТАТ")),
        SpyMatcher(),
        result_limit=5,
    )

    with caplog.at_level(logging.INFO, logger="tg_psyco.search"):  # type: ignore[attr-defined]
        service.search(private_query)

    record = caplog.records[-1]  # type: ignore[attr-defined]
    assert record.event == "search_completed"
    assert record.strategy == SearchStrategy.EXACT.value
    assert record.result_count == 1
    assert record.normalized_length == len(private_query.casefold())
    assert record.duration_ms >= 0
    assert private_query not in record.getMessage()
    assert not hasattr(record, "query")


@pytest.mark.parametrize(
    ("repository", "matcher", "expected_strategy"),
    [
        (
            SpyRepository(fts=[article(2, "ПСИХОЛОГИЯ")]),
            SpyMatcher(),
            SearchStrategy.FTS,
        ),
        (
            SpyRepository(),
            SpyMatcher((FuzzySuggestion(3, "АБСТРАКЦИЯ", 91.0),)),
            SearchStrategy.FUZZY,
        ),
    ],
)
def test_search_logs_fts_and_fuzzy_strategy(
    repository: SpyRepository,
    matcher: SpyMatcher,
    expected_strategy: SearchStrategy,
    caplog: object,
) -> None:
    service = SearchService(repository, matcher, result_limit=5)

    with caplog.at_level(logging.INFO, logger="tg_psyco.search"):  # type: ignore[attr-defined]
        service.search("АБСТРАКЦЫЯ")

    record = caplog.records[-1]  # type: ignore[attr-defined]
    assert record.strategy == expected_strategy.value
    assert record.result_count >= 1


def test_search_failure_logs_only_error_type_and_stage(caplog: object) -> None:
    query = "НЕ ЛОГИРОВАТЬ ЭТОТ ТЕКСТ"
    service = SearchService(
        SpyRepository(error_at="exact"),
        SpyMatcher(),
        result_limit=5,
    )

    with (
        caplog.at_level(logging.ERROR, logger="tg_psyco.search"),  # type: ignore[attr-defined]
        pytest.raises(RuntimeError),
    ):
        service.search(query)

    record = caplog.records[-1]  # type: ignore[attr-defined]
    assert record.event == "search_failed"
    assert record.strategy == SearchStrategy.EXACT.value
    assert record.error_type == "RuntimeError"
    assert query not in record.getMessage()
