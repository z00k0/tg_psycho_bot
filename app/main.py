"""Command-line entry point for server and dictionary administration."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from app.config import ConfigError, Settings
from app.db import (
    DictionaryImportError,
    MigrationError,
    SqliteCapabilityError,
    check_sqlite_fts5_trigram,
    import_dictionary_file,
)
from app.web import delete_configured_webhook, run_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg-psyco",
        description="Telegram psychological dictionary bot",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "check",
        help="validate configuration and required SQLite capabilities",
    )
    subparsers.add_parser(
        "serve",
        help="run the aiohttp Telegram webhook server",
    )
    delete_parser = subparsers.add_parser(
        "delete-webhook",
        help="remove the configured Telegram webhook",
    )
    delete_parser.add_argument(
        "--drop-pending-updates",
        action="store_true",
        help="also discard updates waiting on Telegram",
    )
    import_parser = subparsers.add_parser(
        "import-dictionary",
        help="validate and import dictionary JSON into SQLite",
    )
    import_parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=Path("psychological_dictionary.json"),
    )
    import_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/dictionary.sqlite3"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
    if arguments.command == "check":
        try:
            Settings.from_env()
            check_sqlite_fts5_trigram()
        except (ConfigError, SqliteCapabilityError) as exc:
            parser.error(str(exc))
        print("Configuration and SQLite FTS5 trigram support are valid.")
        return 0
    if arguments.command == "serve":
        try:
            settings = Settings.from_env()
        except ConfigError as exc:
            parser.error(str(exc))
        run_server(settings)
        return 0
    if arguments.command == "delete-webhook":
        try:
            settings = Settings.from_env()
            asyncio.run(
                delete_configured_webhook(
                    settings,
                    drop_pending_updates=arguments.drop_pending_updates,
                )
            )
        except (ConfigError, RuntimeError) as exc:
            parser.error(str(exc))
        print("Webhook removed.")
        return 0
    if arguments.command == "import-dictionary":
        try:
            report = import_dictionary_file(arguments.input, arguments.database)
        except (DictionaryImportError, MigrationError, SqliteCapabilityError) as exc:
            parser.error(str(exc))
        print(
            f"Imported {report.term_count} terms, {report.alias_count} aliases, "
            f"and {report.fts_count} FTS documents into {arguments.database}."
        )
        return 0
    parser.error(f"Unknown command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
