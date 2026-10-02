"""Non-blocking application gateway for synchronous SQLite search."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from os import PathLike

from app.db.connection import open_database
from app.db.migrate import LATEST_SCHEMA_VERSION, apply_migrations, get_schema_version
from app.db.repository import DictionaryRepository
from app.search.fuzzy import FuzzyMatcher
from app.search.models import DictionaryArticle, SearchResult
from app.search.normalize import normalize_query
from app.search.service import SearchService

logger = logging.getLogger("tg_psyco.database")


class GatewayClosedError(RuntimeError):
    """Raised when work is submitted after gateway shutdown."""


@dataclass(slots=True)
class _WorkerState:
    connection: sqlite3.Connection
    repository: DictionaryRepository
    service: SearchService
    fuzzy_choice_count: int


def _create_worker_state(
    database_path: str | PathLike[str],
    result_limit: int,
    max_query_length: int,
) -> _WorkerState:
    connection = open_database(database_path)
    try:
        apply_migrations(connection)
        repository = DictionaryRepository(connection)
        matcher = FuzzyMatcher.from_repository(repository)
        return _WorkerState(
            connection=connection,
            repository=repository,
            service=SearchService(
                repository,
                matcher,
                result_limit=result_limit,
                max_query_length=max_query_length,
            ),
            fuzzy_choice_count=len(matcher.choices),
        )
    except BaseException:
        connection.close()
        raise


def _worker_is_ready(state: _WorkerState) -> bool:
    state.connection.execute("SELECT 1").fetchone()
    term_count = int(state.connection.execute("SELECT COUNT(*) FROM terms").fetchone()[0])
    fts_count = int(
        state.connection.execute("SELECT COUNT(*) FROM terms_fts_docsize").fetchone()[0]
    )
    return (
        get_schema_version(state.connection) == LATEST_SCHEMA_VERSION
        and term_count > 0
        and fts_count == term_count
        and state.fuzzy_choice_count >= term_count
    )


class ThreadedSearchGateway:
    """Run all SQLite-bound operations on one dedicated worker thread."""

    def __init__(
        self,
        executor: ThreadPoolExecutor,
        state: _WorkerState,
    ) -> None:
        self._executor = executor
        self._state = state
        self._closed = False

    @classmethod
    async def create(
        cls,
        database_path: str | PathLike[str],
        *,
        result_limit: int,
        max_query_length: int,
    ) -> ThreadedSearchGateway:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dictionary-db")
        loop = asyncio.get_running_loop()
        try:
            state = await loop.run_in_executor(
                executor,
                _create_worker_state,
                database_path,
                result_limit,
                max_query_length,
            )
        except BaseException:
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        return cls(executor, state)

    async def _run(self, function: object, /, *args: object) -> object:
        if self._closed:
            raise GatewayClosedError("Search gateway is closed")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, partial(function, *args))

    async def search(self, query: str) -> SearchResult:
        result = await self._run(self._state.service.search, query)
        return result  # type: ignore[return-value]

    async def get_article(self, article_id: int) -> DictionaryArticle | None:
        result = await self._run(self._state.repository.get_by_id, article_id)
        return result  # type: ignore[return-value]

    async def get_article_by_term(self, term: str) -> DictionaryArticle | None:
        """Resolve a dictionary redirect without invoking fuzzy or FTS search."""

        normalized = normalize_query(term, max_length=max(1, len(term) * 4))
        result = await self._run(self._state.repository.find_exact, normalized)
        return result  # type: ignore[return-value]

    async def is_ready(self) -> bool:
        if self._closed:
            return False
        try:
            result = await self._run(_worker_is_ready, self._state)
        except (GatewayClosedError, sqlite3.Error) as exc:
            logger.warning(
                "database_readiness_failed",
                extra={
                    "event": "database_readiness_failed",
                    "error_type": type(exc).__name__,
                },
            )
            return False
        return bool(result)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._state.connection.close)
        self._executor.shutdown(wait=True, cancel_futures=True)
