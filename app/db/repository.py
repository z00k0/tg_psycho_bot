"""SQL repository for dictionary articles and exact lookup."""

from __future__ import annotations

import json
import sqlite3

from app.search.fts_query import build_fts_query
from app.search.models import DictionaryArticle, FuzzyChoice

ARTICLE_COLUMNS = """
    t.id,
    t.term,
    t.term_normalized,
    t.heading,
    t.definition,
    t.redirect_to,
    t.letter,
    t.quality_flags_json
"""


def _article_from_row(row: sqlite3.Row) -> DictionaryArticle:
    quality_flags = json.loads(row["quality_flags_json"])
    return DictionaryArticle(
        id=row["id"],
        term=row["term"],
        term_normalized=row["term_normalized"],
        heading=row["heading"],
        definition=row["definition"],
        redirect_to=row["redirect_to"],
        letter=row["letter"],
        quality_flags=tuple(quality_flags),
    )


class DictionaryRepository:
    """Provide parameterized dictionary reads over an existing connection.

    Search methods accept canonical strings produced by ``normalize_query``.
    Connection ownership remains with the caller.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, article_id: int) -> DictionaryArticle | None:
        """Return one article by its stable numeric ID."""

        row = self._connection.execute(
            f"SELECT {ARTICLE_COLUMNS} FROM terms AS t WHERE t.id = ?",
            (article_id,),
        ).fetchone()
        return _article_from_row(row) if row is not None else None

    def find_exact(self, normalized_query: str) -> DictionaryArticle | None:
        """Find a primary term first, then fall back to an exact alias."""

        row = self._connection.execute(
            f"""
            SELECT {ARTICLE_COLUMNS}
            FROM terms AS t
            WHERE t.term_normalized = ?
            LIMIT 1
            """,
            (normalized_query,),
        ).fetchone()
        if row is not None:
            return _article_from_row(row)

        row = self._connection.execute(
            f"""
            SELECT {ARTICLE_COLUMNS}
            FROM term_aliases AS a
            JOIN terms AS t ON t.id = a.term_id
            WHERE a.alias_normalized = ?
            ORDER BY t.id
            LIMIT 1
            """,
            (normalized_query,),
        ).fetchone()
        return _article_from_row(row) if row is not None else None

    def search_fts(
        self,
        normalized_query: str,
        *,
        limit: int,
    ) -> list[DictionaryArticle]:
        """Search dictionary substrings using the FTS5 trigram index.

        Matches in the normalized term or its aliases are always ranked before
        matches found only in article text. Queries shorter than one trigram do
        not execute SQL against the FTS table.
        """

        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if len(normalized_query) < 3:
            return []

        fts_query = build_fts_query(normalized_query)
        rows = self._connection.execute(
            f"""
            SELECT
                {ARTICLE_COLUMNS},
                CASE
                    WHEN instr(t.term_normalized, ?) > 0
                      OR instr(t.search_blob, ?) > 0
                    THEN 0
                    ELSE 1
                END AS match_priority,
                bm25(terms_fts, 10.0, 2.0, 1.0, 8.0) AS relevance
            FROM terms_fts
            JOIN terms AS t ON t.id = terms_fts.rowid
            WHERE terms_fts MATCH ?
            ORDER BY
                match_priority ASC,
                relevance ASC,
                t.term_normalized ASC,
                t.id ASC
            LIMIT ?
            """,
            (normalized_query, normalized_query, fts_query, limit),
        ).fetchall()
        return [_article_from_row(row) for row in rows]

    def load_fuzzy_choices(self) -> tuple[FuzzyChoice, ...]:
        """Load primary terms and aliases for one immutable in-memory index."""

        rows = self._connection.execute(
            """
            SELECT article_id, term, normalized
            FROM (
                SELECT
                    t.id AS article_id,
                    t.term AS term,
                    t.term_normalized AS normalized,
                    0 AS variant_order
                FROM terms AS t

                UNION ALL

                SELECT
                    t.id AS article_id,
                    t.term AS term,
                    a.alias_normalized AS normalized,
                    1 AS variant_order
                FROM term_aliases AS a
                JOIN terms AS t ON t.id = a.term_id
            )
            ORDER BY article_id, variant_order, normalized
            """
        ).fetchall()
        return tuple(
            FuzzyChoice(
                article_id=row["article_id"],
                term=row["term"],
                normalized=row["normalized"],
            )
            for row in rows
        )
