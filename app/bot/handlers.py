"""Aiogram handlers for dictionary search and article callbacks."""

from __future__ import annotations

import logging
from typing import Protocol

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import TermCallback
from app.bot.formatting import format_article_messages
from app.bot.keyboards import redirect_keyboard, term_keyboard
from app.search.fuzzy import MAX_FUZZY_SUGGESTIONS
from app.search.models import (
    DictionaryArticle,
    ExactMatch,
    FtsMatches,
    InvalidQuery,
    InvalidQueryReason,
    SearchResult,
    Suggestions,
)

logger = logging.getLogger("tg_psyco.telegram")

START_TEXT = (
    "Отправьте психологический термин, и я найду его определение. "
    "Можно вводить термин целиком или его часть."
)
HELP_TEXT = (
    "Введите название психологического термина обычным сообщением. "
    "Если точного совпадения нет, я предложу подходящие статьи или похожие варианты."
)
FTS_RESULTS_TEXT = "Найдены подходящие статьи:"
FUZZY_RESULTS_TEXT = "Возможно, вы имели в виду…"
NOT_FOUND_TEXT = "Ничего не найдено. Попробуйте изменить запрос."
NON_TEXT_TEXT = "Отправьте термин текстовым сообщением."
INTERNAL_ERROR_TEXT = "Не удалось выполнить поиск. Попробуйте ещё раз позже."
ARTICLE_NOT_FOUND_TEXT = "Статья не найдена. Возможно, словарь был обновлён."
INVALID_CALLBACK_TEXT = "Некорректная кнопка выбора статьи."


class BotSearchGateway(Protocol):
    """Async application boundary consumed by Telegram handlers."""

    async def search(self, query: str) -> SearchResult: ...

    async def get_article(self, article_id: int) -> DictionaryArticle | None: ...

    async def get_article_by_term(self, term: str) -> DictionaryArticle | None: ...


async def _send_article(
    target: Message,
    article: DictionaryArticle,
    gateway: BotSearchGateway,
) -> None:
    reply_markup = None
    if article.redirect_to is not None:
        try:
            redirect = await gateway.get_article_by_term(article.redirect_to)
        except Exception as exc:
            logger.warning(
                "redirect_lookup_failed",
                extra={
                    "event": "redirect_lookup_failed",
                    "article_id": article.id,
                    "error_type": type(exc).__name__,
                },
            )
        else:
            if redirect is not None and redirect.id != article.id:
                reply_markup = redirect_keyboard(redirect.id, redirect.term)

    messages = format_article_messages(article)
    for index, text in enumerate(messages):
        arguments = {"parse_mode": ParseMode.HTML}
        if reply_markup is not None and index == len(messages) - 1:
            arguments["reply_markup"] = reply_markup
        await target.answer(text, **arguments)


async def handle_start(message: Message) -> None:
    await message.answer(START_TEXT)


async def handle_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


def _invalid_query_text(result: InvalidQuery) -> str:
    if result.reason is InvalidQueryReason.TOO_LONG:
        return "Запрос слишком длинный. Сократите его и попробуйте снова."
    if result.reason is InvalidQueryReason.EMPTY:
        return "Введите термин, состоящий из букв или цифр."
    return "Не удалось распознать запрос. Введите термин текстом."


async def handle_text_search(message: Message, gateway: BotSearchGateway) -> None:
    if message.text is None:
        await message.answer(NON_TEXT_TEXT)
        return
    try:
        result = await gateway.search(message.text)
    except Exception as exc:
        logger.error(
            "handler_search_failed",
            extra={
                "event": "handler_search_failed",
                "error_type": type(exc).__name__,
            },
        )
        await message.answer(INTERNAL_ERROR_TEXT)
        return

    if isinstance(result, ExactMatch):
        await _send_article(message, result.article, gateway)
        return
    if isinstance(result, FtsMatches):
        keyboard = term_keyboard((article.id, article.term) for article in result.articles)
        await message.answer(FTS_RESULTS_TEXT, reply_markup=keyboard)
        return
    if isinstance(result, Suggestions):
        if not result.suggestions:
            await message.answer(NOT_FOUND_TEXT)
            return
        keyboard = term_keyboard(
            ((item.article_id, item.term) for item in result.suggestions),
            limit=MAX_FUZZY_SUGGESTIONS,
        )
        await message.answer(FUZZY_RESULTS_TEXT, reply_markup=keyboard)
        return
    await message.answer(_invalid_query_text(result))


async def handle_non_text(message: Message) -> None:
    await message.answer(NON_TEXT_TEXT)


async def handle_term_callback(
    callback: CallbackQuery,
    callback_data: TermCallback,
    gateway: BotSearchGateway,
) -> None:
    if callback_data.article_id < 1:
        await callback.answer(INVALID_CALLBACK_TEXT, show_alert=True)
        return
    try:
        article = await gateway.get_article(callback_data.article_id)
    except Exception as exc:
        logger.error(
            "article_lookup_failed",
            extra={
                "event": "article_lookup_failed",
                "error_type": type(exc).__name__,
            },
        )
        await callback.answer(INTERNAL_ERROR_TEXT, show_alert=True)
        return
    if article is None:
        await callback.answer(ARTICLE_NOT_FOUND_TEXT, show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await _send_article(callback.message, article, gateway)


async def handle_invalid_term_callback(callback: CallbackQuery) -> None:
    await callback.answer(INVALID_CALLBACK_TEXT, show_alert=True)


def create_router() -> Router:
    router = Router(name="dictionary")
    private_chat = F.chat.type == "private"
    router.message.register(handle_start, CommandStart(), private_chat)
    router.message.register(handle_help, Command("help"), private_chat)
    router.message.register(handle_text_search, F.text, private_chat)
    router.message.register(handle_non_text, private_chat)
    router.callback_query.register(handle_term_callback, TermCallback.filter())
    router.callback_query.register(
        handle_invalid_term_callback,
        F.data.startswith("term:"),
    )
    return router


router = create_router()
