"""Typed callback payloads used by dictionary keyboards."""

from aiogram.filters.callback_data import CallbackData


class TermCallback(CallbackData, prefix="term"):
    article_id: int
