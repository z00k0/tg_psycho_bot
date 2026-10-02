from __future__ import annotations

import re
from html import unescape

import pytest

from app.bot.callbacks import TermCallback
from app.bot.formatting import format_article_messages
from app.bot.keyboards import MAX_BUTTON_TEXT_LENGTH, term_keyboard
from app.search.models import DictionaryArticle


def article(*, term: str = "ТЕРМИН", definition: str = "Определение") -> DictionaryArticle:
    return DictionaryArticle(
        id=42,
        term=term,
        term_normalized="термин",
        heading=term,
        definition=definition,
        redirect_to=None,
        letter="Т",
        quality_flags=(),
    )


def rendered_text(messages: tuple[str, ...]) -> str:
    without_tags = "".join(re.sub(r"</?b>", "", message) for message in messages)
    return unescape(without_tags)


def test_article_html_escapes_term_and_definition() -> None:
    messages = format_article_messages(
        article(term="ТЕСТ <A&B>", definition="Значение: 2 < 3 & 5 > 4"),
    )

    assert messages == (
        "<b>ТЕСТ &lt;A&amp;B&gt;</b>\n\n"
        "Значение: 2 &lt; 3 &amp; 5 &gt; 4",
    )


def test_long_definition_is_split_without_text_loss() -> None:
    source = ("абв & <тест>\n" * 80) + "конец"

    messages = format_article_messages(article(definition=source), limit=80)

    assert len(messages) > 2
    assert all(len(message) <= 80 for message in messages)
    assert rendered_text(messages) == f"ТЕРМИН\n\n{source}"
    assert all("<" not in message.replace("<b>", "").replace("</b>", "") for message in messages)


def test_very_long_term_falls_back_to_safe_plain_chunks() -> None:
    source = article(term="<&>" * 20, definition="Определение & продолжение")

    messages = format_article_messages(source, limit=32)

    assert all(len(message) <= 32 for message in messages)
    assert rendered_text(messages) == f"{source.term}\n\n{source.definition}"


@pytest.mark.parametrize("limit", [0, 15, True, 20.5])
def test_message_limit_is_validated(limit: object) -> None:
    with pytest.raises(ValueError, match="at least"):
        format_article_messages(article(), limit=limit)  # type: ignore[arg-type]


def test_term_callback_uses_only_numeric_article_id() -> None:
    packed = TermCallback(article_id=123).pack()

    assert packed == "term:123"
    assert len(packed.encode()) <= 64


def test_keyboard_uses_one_button_per_row_and_limit() -> None:
    keyboard = term_keyboard(
        [(1, "ПАМЯТЬ"), (2, "МЫШЛЕНИЕ"), (3, "ВНИМАНИЕ"), (4, "ЭМОЦИЯ")],
        limit=3,
    )

    assert len(keyboard.inline_keyboard) == 3
    assert all(len(row) == 1 for row in keyboard.inline_keyboard)
    assert [row[0].callback_data for row in keyboard.inline_keyboard] == [
        "term:1",
        "term:2",
        "term:3",
    ]


def test_long_button_text_is_readable_and_bounded() -> None:
    keyboard = term_keyboard([(1, "А" * 100)])
    text = keyboard.inline_keyboard[0][0].text

    assert len(text) == MAX_BUTTON_TEXT_LENGTH
    assert text.endswith("…")
