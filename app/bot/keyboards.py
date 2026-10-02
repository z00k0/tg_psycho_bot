"""Inline keyboards for selecting dictionary articles."""

from __future__ import annotations

from collections.abc import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import TermCallback

MAX_BUTTON_TEXT_LENGTH = 64


def _button_text(term: str) -> str:
    if len(term) <= MAX_BUTTON_TEXT_LENGTH:
        return term
    return f"{term[: MAX_BUTTON_TEXT_LENGTH - 1]}…"


def term_keyboard(
    articles: Iterable[tuple[int, str]],
    *,
    limit: int | None = None,
) -> InlineKeyboardMarkup:
    """Build a vertical article keyboard using stable numeric callback IDs."""

    rows: list[list[InlineKeyboardButton]] = []
    for article_id, term in articles:
        if limit is not None and len(rows) >= limit:
            break
        rows.append(
            [
                InlineKeyboardButton(
                    text=_button_text(term),
                    callback_data=TermCallback(article_id=article_id).pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
