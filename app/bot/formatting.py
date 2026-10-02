"""Safe Telegram HTML formatting and message splitting."""

from __future__ import annotations

from html import escape

from app.search.models import DictionaryArticle

TELEGRAM_TEXT_LIMIT = 4096
MIN_MESSAGE_LIMIT = 16


def _escaped_prefix_end(text: str, start: int, budget: int) -> int:
    escaped_length = 0
    end = start
    while end < len(text):
        character_length = len(escape(text[end], quote=False))
        if escaped_length + character_length > budget:
            break
        escaped_length += character_length
        end += 1
    return end


def _plain_html_chunks(text: str, limit: int) -> tuple[str, ...]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = _escaped_prefix_end(text, start, limit)
        if end == start:
            raise ValueError("message limit is too small for escaped text")
        chunks.append(escape(text[start:end], quote=False))
        start = end
    return tuple(chunks)


def format_article_messages(
    article: DictionaryArticle,
    *,
    limit: int = TELEGRAM_TEXT_LIMIT,
) -> tuple[str, ...]:
    """Format an article as valid HTML chunks within Telegram's text limit."""

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < MIN_MESSAGE_LIMIT:
        raise ValueError(f"limit must be an integer of at least {MIN_MESSAGE_LIMIT}")

    escaped_term = escape(article.term, quote=False)
    prefix = f"<b>{escaped_term}</b>\n\n"
    if len(prefix) > limit:
        return _plain_html_chunks(f"{article.term}\n\n{article.definition}", limit)

    messages: list[str] = []
    start = 0
    first_end = _escaped_prefix_end(article.definition, start, limit - len(prefix))
    messages.append(prefix + escape(article.definition[start:first_end], quote=False))
    start = first_end
    while start < len(article.definition):
        end = _escaped_prefix_end(article.definition, start, limit)
        if end == start:
            raise ValueError("message limit is too small for escaped text")
        messages.append(escape(article.definition[start:end], quote=False))
        start = end
    return tuple(messages)
