from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteWebhook,
    SendMessage,
    SetWebhook,
    TelegramMethod,
)
from aiogram.types import Chat, Message
from aiohttp.test_utils import TestClient, TestServer

from app.config import Settings
from app.db.connection import database_connection
from app.db.import_dictionary import import_dictionary_file
from app.db.repository import DictionaryRepository
from app.search.models import (
    DictionaryArticle,
    InvalidQuery,
    InvalidQueryReason,
    SearchDiagnostics,
    SearchStrategy,
)
from app.web import (
    ALLOWED_UPDATES,
    WEBHOOK_HANDLER_KEY,
    create_application,
    delete_configured_webhook,
)


class RecordingSession(BaseSession):
    def __init__(self, *, set_webhook_result: bool = True) -> None:
        super().__init__()
        self.methods: list[TelegramMethod[Any]] = []
        self.closed = False
        self.set_webhook_result = set_webhook_result

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        self.methods.append(method)
        if isinstance(method, SetWebhook):
            return self.set_webhook_result
        if isinstance(method, DeleteWebhook):
            return True
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.methods) + 100,
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        raise AssertionError(f"Unexpected Bot API method: {type(method).__name__}")

    async def close(self) -> None:
        self.closed = True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65_536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes]:
        if False:
            yield b""


class FakeGateway:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.closed = False
        self.search_calls = 0

    async def search(self, query: str) -> InvalidQuery:
        self.search_calls += 1
        return InvalidQuery(
            InvalidQueryReason.INVALID,
            "invalid",
            SearchDiagnostics(SearchStrategy.INVALID, None, 0),
        )

    async def get_article(self, article_id: int) -> DictionaryArticle | None:
        return None

    async def get_article_by_term(self, term: str) -> DictionaryArticle | None:
        return None

    async def is_ready(self) -> bool:
        return self.ready and not self.closed

    async def close(self) -> None:
        self.closed = True


def settings(database_path: Path) -> Settings:
    return Settings(
        bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDE",
        base_webhook_url="https://bot.example.test",
        webhook_path="/telegram/webhook",
        webhook_secret="integration_secret-123",
        host="127.0.0.1",
        port=8080,
        database_path=database_path,
        search_result_limit=5,
        max_query_length=200,
    )


async def wait_for_methods(
    session: RecordingSession,
    method_type: type[TelegramMethod[Any]],
    count: int,
) -> list[TelegramMethod[Any]]:
    for _ in range(100):
        methods = [method for method in session.methods if isinstance(method, method_type)]
        if len(methods) >= count:
            return methods
        await asyncio.sleep(0.01)
    raise AssertionError(f"Timed out waiting for {count} {method_type.__name__} calls")


@pytest.mark.asyncio
async def test_application_lifecycle_health_readiness_and_webhook_secret(
    workspace_tmp_path: Path,
) -> None:
    session = RecordingSession()
    bot = Bot(settings(workspace_tmp_path / "db.sqlite3").bot_token, session=session)
    gateway = FakeGateway()

    async def gateway_factory(_: Settings) -> FakeGateway:
        return gateway

    application = create_application(
        settings(workspace_tmp_path / "db.sqlite3"),
        bot=bot,
        gateway_factory=gateway_factory,
    )
    handler = application[WEBHOOK_HANDLER_KEY]
    assert handler.handle_in_background is True
    assert handler.secret_token == "integration_secret-123"

    client = TestClient(TestServer(application))
    await client.start_server()
    try:
        health_response = await client.get("/healthz")
        ready_response = await client.get("/readyz")
        rejected_response = await client.post(
            "/telegram/webhook",
            json={"update_id": 1},
        )
        accepted_response = await client.post(
            "/telegram/webhook",
            json={
                "update_id": 2,
                "edited_message": {
                    "message_id": 1,
                    "date": 0,
                    "chat": {"id": 1, "type": "private"},
                },
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": "integration_secret-123"},
        )

        assert health_response.status == 200
        assert await health_response.json() == {"status": "ok"}
        assert ready_response.status == 200
        assert await ready_response.json() == {"status": "ready"}
        assert rejected_response.status == 401
        assert accepted_response.status == 200
        assert gateway.search_calls == 0

        set_calls = [method for method in session.methods if isinstance(method, SetWebhook)]
        assert len(set_calls) == 1
        assert set_calls[0].url == "https://bot.example.test/telegram/webhook"
        assert set_calls[0].secret_token == "integration_secret-123"
        assert set_calls[0].allowed_updates == ALLOWED_UPDATES
        assert not any(isinstance(method, DeleteWebhook) for method in session.methods)
    finally:
        await client.close()

    assert gateway.closed is True


@pytest.mark.asyncio
async def test_webhook_fuzzy_button_returns_real_definition_without_network(
    workspace_tmp_path: Path,
) -> None:
    source = Path(__file__).parents[2] / "psychological_dictionary.json"
    database_path = workspace_tmp_path / "webhook.sqlite3"
    import_dictionary_file(source, database_path)
    configured = settings(database_path)
    session = RecordingSession()
    bot = Bot(configured.bot_token, session=session)
    client = TestClient(TestServer(create_application(configured, bot=bot)))
    await client.start_server()
    headers = {"X-Telegram-Bot-Api-Secret-Token": configured.webhook_secret}
    user = {"id": 42, "is_bot": False, "first_name": "Tester"}
    chat = {"id": 42, "type": "private"}
    try:
        response = await client.post(
            configured.webhook_path,
            headers=headers,
            json={
                "update_id": 100,
                "message": {
                    "message_id": 10,
                    "date": 1_700_000_000,
                    "from": user,
                    "chat": chat,
                    "text": "абстракцыя",
                },
            },
        )
        assert response.status == 200
        sent = await wait_for_methods(session, SendMessage, 1)
        choice_message = sent[0]
        assert isinstance(choice_message, SendMessage)
        assert choice_message.text == "Возможно, вы имели в виду…"
        assert choice_message.reply_markup is not None
        callback_data = choice_message.reply_markup.inline_keyboard[0][0].callback_data
        assert callback_data is not None
        selected_id = int(callback_data.removeprefix("term:"))

        callback_response = await client.post(
            configured.webhook_path,
            headers=headers,
            json={
                "update_id": 101,
                "callback_query": {
                    "id": "callback-1",
                    "from": user,
                    "chat_instance": "test-instance",
                    "data": callback_data,
                    "message": {
                        "message_id": 11,
                        "date": 1_700_000_001,
                        "from": {
                            "id": 123456,
                            "is_bot": True,
                            "first_name": "Dictionary",
                        },
                        "chat": chat,
                        "text": choice_message.text,
                    },
                },
            },
        )
        assert callback_response.status == 200
        sent = await wait_for_methods(session, SendMessage, 2)
        await wait_for_methods(session, AnswerCallbackQuery, 1)
        with database_connection(database_path) as connection:
            article = DictionaryRepository(connection).get_by_id(selected_id)
        assert article is not None
        assert escape(article.term) in sent[1].text
        assert escape(article.definition[:40]) in sent[1].text
    finally:
        await client.close()

    assert session.closed is True
    assert session.closed is True
    assert not any(isinstance(method, DeleteWebhook) for method in session.methods)


@pytest.mark.asyncio
async def test_webhook_redirect_button_opens_target_article(
    workspace_tmp_path: Path,
) -> None:
    source = Path(__file__).parents[2] / "psychological_dictionary.json"
    database_path = workspace_tmp_path / "redirect.sqlite3"
    import_dictionary_file(source, database_path)
    configured = settings(database_path)
    session = RecordingSession()
    bot = Bot(configured.bot_token, session=session)
    client = TestClient(TestServer(create_application(configured, bot=bot)))
    await client.start_server()
    headers = {"X-Telegram-Bot-Api-Secret-Token": configured.webhook_secret}
    user = {"id": 42, "is_bot": False, "first_name": "Tester"}
    chat = {"id": 42, "type": "private"}
    try:
        response = await client.post(
            configured.webhook_path,
            headers=headers,
            json={
                "update_id": 200,
                "message": {
                    "message_id": 20,
                    "date": 1_700_000_000,
                    "from": user,
                    "chat": chat,
                    "text": "ядерная плоскость",
                },
            },
        )
        assert response.status == 200
        sent = await wait_for_methods(session, SendMessage, 1)
        redirect_message = sent[0]
        assert isinstance(redirect_message, SendMessage)
        assert redirect_message.reply_markup is not None
        button = redirect_message.reply_markup.inline_keyboard[0][0]
        assert button.text == "Перейти: СТЕРЕОПСИС"
        assert button.callback_data is not None

        callback_response = await client.post(
            configured.webhook_path,
            headers=headers,
            json={
                "update_id": 201,
                "callback_query": {
                    "id": "redirect-callback",
                    "from": user,
                    "chat_instance": "test-instance",
                    "data": button.callback_data,
                    "message": {
                        "message_id": 21,
                        "date": 1_700_000_001,
                        "from": {
                            "id": 123456,
                            "is_bot": True,
                            "first_name": "Dictionary",
                        },
                        "chat": chat,
                        "text": redirect_message.text,
                    },
                },
            },
        )
        assert callback_response.status == 200
        sent = await wait_for_methods(session, SendMessage, 2)
        await wait_for_methods(session, AnswerCallbackQuery, 1)
        assert "СТЕРЕОПСИС" in sent[1].text
    finally:
        await client.close()

    assert session.closed is True


@pytest.mark.asyncio
async def test_administrative_webhook_removal_is_explicit(
    workspace_tmp_path: Path,
) -> None:
    configured = settings(workspace_tmp_path / "db.sqlite3")
    session = RecordingSession()
    bot = Bot(configured.bot_token, session=session)

    await delete_configured_webhook(
        configured,
        drop_pending_updates=True,
        bot=bot,
    )

    delete_calls = [method for method in session.methods if isinstance(method, DeleteWebhook)]
    assert len(delete_calls) == 1
    assert delete_calls[0].drop_pending_updates is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_readiness_is_unavailable_when_dictionary_is_not_ready(
    workspace_tmp_path: Path,
) -> None:
    configured = settings(workspace_tmp_path / "db.sqlite3")
    session = RecordingSession()
    bot = Bot(configured.bot_token, session=session)
    gateway = FakeGateway(ready=False)

    async def gateway_factory(_: Settings) -> FakeGateway:
        return gateway

    client = TestClient(
        TestServer(
            create_application(
                configured,
                bot=bot,
                gateway_factory=gateway_factory,
            )
        )
    )
    await client.start_server()
    try:
        response = await client.get("/readyz")
        assert response.status == 503
        assert await response.json() == {"status": "not_ready"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_failed_webhook_registration_closes_initialized_gateway(
    workspace_tmp_path: Path,
) -> None:
    configured = settings(workspace_tmp_path / "db.sqlite3")
    session = RecordingSession(set_webhook_result=False)
    bot = Bot(configured.bot_token, session=session)
    gateway = FakeGateway()

    async def gateway_factory(_: Settings) -> FakeGateway:
        return gateway

    client = TestClient(
        TestServer(
            create_application(
                configured,
                bot=bot,
                gateway_factory=gateway_factory,
            )
        )
    )
    with pytest.raises(RuntimeError, match="rejected webhook registration"):
        await client.start_server()
    await client.close()

    assert gateway.closed is True
