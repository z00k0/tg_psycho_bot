from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
from typing import Any

import pytest
from aiogram.enums import ParseMode

from app.bot.callbacks import TermCallback
from app.bot.handlers import (
    ARTICLE_NOT_FOUND_TEXT,
    FTS_RESULTS_TEXT,
    FUZZY_RESULTS_TEXT,
    HELP_TEXT,
    INTERNAL_ERROR_TEXT,
    INVALID_CALLBACK_TEXT,
    NON_TEXT_TEXT,
    NOT_FOUND_TEXT,
    START_TEXT,
    create_router,
    handle_help,
    handle_invalid_term_callback,
    handle_non_text,
    handle_start,
    handle_term_callback,
    handle_text_search,
)
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


def article(
    article_id: int = 1,
    term: str = "ПАМЯТЬ",
    definition: str = "Текст",
) -> DictionaryArticle:
    return DictionaryArticle(
        id=article_id,
        term=term,
        term_normalized=term.casefold().replace("ё", "е"),
        heading=term,
        definition=definition,
        redirect_to=None,
        letter=term[0],
        quality_flags=(),
    )


def diagnostics(strategy: SearchStrategy, count: int) -> SearchDiagnostics:
    return SearchDiagnostics(strategy=strategy, normalized_length=6, result_count=count)


@dataclass
class FakeMessage:
    text: str | None = None
    answers: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append((text, kwargs))


class FakeGateway:
    def __init__(
        self,
        *,
        result: SearchResult | None = None,
        stored_article: DictionaryArticle | None = None,
        fail_search: bool = False,
        fail_get: bool = False,
    ) -> None:
        self.result = result
        self.stored_article = stored_article
        self.fail_search = fail_search
        self.fail_get = fail_get
        self.search_calls: list[str] = []
        self.get_calls: list[int] = []

    async def search(self, query: str) -> SearchResult:
        self.search_calls.append(query)
        if self.fail_search:
            raise RuntimeError("search failed")
        assert self.result is not None
        return self.result

    async def get_article(self, article_id: int) -> DictionaryArticle | None:
        self.get_calls.append(article_id)
        if self.fail_get:
            raise RuntimeError("database failed")
        return self.stored_article


@dataclass
class FakeCallback:
    message: FakeMessage | None = None
    answers: list[tuple[str | None, dict[str, Any]]] = field(default_factory=list)

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_start_and_help_messages() -> None:
    start_message = FakeMessage()
    help_message = FakeMessage()

    await handle_start(start_message)  # type: ignore[arg-type]
    await handle_help(help_message)  # type: ignore[arg-type]

    assert start_message.answers == [(START_TEXT, {})]
    assert help_message.answers == [(HELP_TEXT, {})]


@pytest.mark.asyncio
async def test_exact_match_sends_escaped_article_without_keyboard() -> None:
    expected = article(term="ПАМЯТЬ <И>", definition="A & B")
    result = ExactMatch(expected, diagnostics(SearchStrategy.EXACT, 1))
    message = FakeMessage(text="память")

    await handle_text_search(message, FakeGateway(result=result))  # type: ignore[arg-type]

    assert message.answers[0][0] == "<b>ПАМЯТЬ &lt;И&gt;</b>\n\nA &amp; B"
    assert "reply_markup" not in message.answers[0][1]
    assert message.answers[0][1]["parse_mode"] is ParseMode.HTML


@pytest.mark.asyncio
async def test_fts_matches_send_article_selection_keyboard() -> None:
    matches = (article(1, "ПАМЯТЬ"), article(2, "ПАМЯТЬ ЭМОЦИОНАЛЬНАЯ"))
    result = FtsMatches(matches, diagnostics(SearchStrategy.FTS, 2))
    message = FakeMessage(text="памят")

    await handle_text_search(message, FakeGateway(result=result))  # type: ignore[arg-type]

    text, arguments = message.answers[0]
    keyboard = arguments["reply_markup"]
    assert text == FTS_RESULTS_TEXT
    assert [row[0].callback_data for row in keyboard.inline_keyboard] == ["term:1", "term:2"]


@pytest.mark.asyncio
async def test_fuzzy_result_sends_phrase_and_at_most_three_buttons() -> None:
    suggestions = tuple(
        FuzzySuggestion(article_id=index, term=f"ТЕРМИН {index}", score=100 - index)
        for index in range(1, 5)
    )
    result = Suggestions(suggestions, diagnostics(SearchStrategy.FUZZY, 4))
    message = FakeMessage(text="термен")

    await handle_text_search(message, FakeGateway(result=result))  # type: ignore[arg-type]

    text, arguments = message.answers[0]
    assert text == FUZZY_RESULTS_TEXT
    assert len(arguments["reply_markup"].inline_keyboard) == 3


@pytest.mark.asyncio
async def test_empty_suggestions_send_not_found_text() -> None:
    result = Suggestions((), diagnostics(SearchStrategy.FUZZY, 0))
    message = FakeMessage(text="неизвестно")

    await handle_text_search(message, FakeGateway(result=result))  # type: ignore[arg-type]

    assert message.answers == [(NOT_FOUND_TEXT, {})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "fragment"),
    [
        (InvalidQueryReason.EMPTY, "Введите термин"),
        (InvalidQueryReason.TOO_LONG, "слишком длинный"),
        (InvalidQueryReason.INVALID, "Не удалось распознать"),
    ],
)
async def test_invalid_query_gets_specific_user_message(
    reason: InvalidQueryReason,
    fragment: str,
) -> None:
    result = InvalidQuery(
        reason,
        "internal normalization message",
        diagnostics(SearchStrategy.INVALID, 0),
    )
    message = FakeMessage(text="query")

    await handle_text_search(message, FakeGateway(result=result))  # type: ignore[arg-type]

    assert fragment in message.answers[0][0]
    assert "internal normalization message" not in message.answers[0][0]


@pytest.mark.asyncio
async def test_search_failure_gets_controlled_message() -> None:
    message = FakeMessage(text="память")

    await handle_text_search(message, FakeGateway(fail_search=True))  # type: ignore[arg-type]

    assert message.answers == [(INTERNAL_ERROR_TEXT, {})]


@pytest.mark.asyncio
async def test_non_text_message_gets_short_instruction() -> None:
    message = FakeMessage()

    await handle_non_text(message)  # type: ignore[arg-type]

    assert message.answers == [(NON_TEXT_TEXT, {})]


@pytest.mark.asyncio
async def test_valid_callback_answers_and_sends_full_article() -> None:
    definition = "<&>" * 2_000
    stored = article(7, "ТЕСТ <7>", definition)
    message = FakeMessage()
    callback = FakeCallback(message=message)
    gateway = FakeGateway(stored_article=stored)

    await handle_term_callback(  # type: ignore[arg-type]
        callback,
        TermCallback(article_id=7),
        gateway,
    )

    assert callback.answers == [(None, {})]
    assert gateway.get_calls == [7]
    assert len(message.answers) > 1
    assert all(len(text) <= 4096 for text, _ in message.answers)
    rendered = "".join(text.replace("<b>", "").replace("</b>", "") for text, _ in message.answers)
    assert unescape(rendered) == f"{stored.term}\n\n{definition}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("article_id", "stored", "fail", "expected_text"),
    [
        (0, None, False, INVALID_CALLBACK_TEXT),
        (999, None, False, ARTICLE_NOT_FOUND_TEXT),
        (1, None, True, INTERNAL_ERROR_TEXT),
    ],
)
async def test_callback_error_scenarios_always_answer(
    article_id: int,
    stored: DictionaryArticle | None,
    fail: bool,
    expected_text: str,
) -> None:
    callback = FakeCallback(message=FakeMessage())
    gateway = FakeGateway(stored_article=stored, fail_get=fail)

    await handle_term_callback(  # type: ignore[arg-type]
        callback,
        TermCallback(article_id=article_id),
        gateway,
    )

    assert callback.answers == [(expected_text, {"show_alert": True})]


@pytest.mark.asyncio
async def test_malformed_term_callback_is_answered() -> None:
    callback = FakeCallback()

    await handle_invalid_term_callback(callback)  # type: ignore[arg-type]

    assert callback.answers == [(INVALID_CALLBACK_TEXT, {"show_alert": True})]


def test_router_can_be_created_without_bot_or_network() -> None:
    router = create_router()

    assert router.name == "dictionary"
    assert len(router.message.handlers) == 4
    assert len(router.callback_query.handlers) == 2
