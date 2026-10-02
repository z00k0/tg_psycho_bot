from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from app.bot.gateway import GatewayClosedError, ThreadedSearchGateway
from app.db.connection import database_connection
from app.db.import_dictionary import DictionaryEntry, DictionaryPayload, import_dictionary_payload
from app.db.migrate import apply_migrations
from app.search.models import ExactMatch


def create_dictionary(database_path: Path) -> None:
    payload = DictionaryPayload(
        schema_version=1,
        entries=(
            DictionaryEntry(
                id=1,
                term="ПАМЯТЬ",
                term_normalized="память",
                aliases=("запоминание",),
                letter="П",
                heading="ПАМЯТЬ",
                definition="Способность сохранять и воспроизводить опыт.",
                redirect_to=None,
                quality_flags=(),
            ),
            DictionaryEntry(
                id=2,
                term="МЫШЛЕНИЕ",
                term_normalized="мышление",
                aliases=(),
                letter="М",
                heading="МЫШЛЕНИЕ",
                definition="Познавательный процесс.",
                redirect_to=None,
                quality_flags=(),
            ),
        ),
    )
    with database_connection(database_path) as connection:
        apply_migrations(connection)
        import_dictionary_payload(connection, payload)


@pytest.mark.asyncio
async def test_gateway_uses_worker_owned_sqlite_connection(
    workspace_tmp_path: Path,
) -> None:
    database_path = workspace_tmp_path / "dictionary.sqlite3"
    create_dictionary(database_path)
    gateway = await ThreadedSearchGateway.create(
        database_path,
        result_limit=5,
        max_query_length=200,
    )
    try:
        result = await gateway.search("ПАМЯТЬ")
        stored = await gateway.get_article(1)
        exact_alias = await gateway.get_article_by_term("запоминание")

        assert isinstance(result, ExactMatch)
        assert result.article.id == 1
        assert stored is not None
        assert stored.definition == "Способность сохранять и воспроизводить опыт."
        assert exact_alias is not None
        assert exact_alias.id == 1
        assert await gateway.is_ready() is True
    finally:
        await gateway.close()


@pytest.mark.asyncio
async def test_empty_database_is_migrated_but_not_ready(
    workspace_tmp_path: Path,
) -> None:
    gateway = await ThreadedSearchGateway.create(
        workspace_tmp_path / "empty.sqlite3",
        result_limit=5,
        max_query_length=200,
    )
    try:
        assert await gateway.is_ready() is False
    finally:
        await gateway.close()


@pytest.mark.asyncio
async def test_gateway_work_does_not_block_event_loop(workspace_tmp_path: Path) -> None:
    database_path = workspace_tmp_path / "dictionary.sqlite3"
    create_dictionary(database_path)
    gateway = await ThreadedSearchGateway.create(
        database_path,
        result_limit=5,
        max_query_length=200,
    )
    original_search = gateway._state.service.search  # noqa: SLF001

    def slow_search(query: str) -> object:
        time.sleep(0.1)
        return original_search(query)

    gateway._state.service.search = slow_search  # type: ignore[method-assign]  # noqa: SLF001
    try:
        search_task = asyncio.create_task(gateway.search("память"))
        await asyncio.sleep(0.02)

        assert search_task.done() is False
        assert isinstance(await search_task, ExactMatch)
    finally:
        await gateway.close()


@pytest.mark.asyncio
async def test_gateway_close_is_idempotent_and_rejects_new_work(
    workspace_tmp_path: Path,
) -> None:
    gateway = await ThreadedSearchGateway.create(
        workspace_tmp_path / "empty.sqlite3",
        result_limit=5,
        max_query_length=200,
    )

    await gateway.close()
    await gateway.close()

    assert await gateway.is_ready() is False
    with pytest.raises(GatewayClosedError):
        await gateway.search("память")
