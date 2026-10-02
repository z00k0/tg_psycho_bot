"""Telegram bot presentation layer."""

from app.bot.callbacks import TermCallback
from app.bot.formatting import TELEGRAM_TEXT_LIMIT, format_article_messages
from app.bot.gateway import GatewayClosedError, ThreadedSearchGateway
from app.bot.handlers import BotSearchGateway, create_router, router
from app.bot.keyboards import term_keyboard

__all__ = [
    "TELEGRAM_TEXT_LIMIT",
    "BotSearchGateway",
    "GatewayClosedError",
    "TermCallback",
    "ThreadedSearchGateway",
    "create_router",
    "format_article_messages",
    "router",
    "term_keyboard",
]
