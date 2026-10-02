#!/usr/bin/env python3
"""Convert the complete PDF edition of the psychology dictionary to JSON.

The PDF has a usable text layer and preserves font metadata. Dictionary entry
headings begin with bold uppercase text, while the body and internal subheads do
not. Only the dictionary pages are parsed; the front matter and indexes are
excluded explicitly.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from convert_dictionary import (
    clean_term,
    compact_spaces,
    convert_source_lines,
    is_heading_term,
)

DEFAULT_FIRST_PAGE = 9
DEFAULT_LAST_PAGE = 573


class PdfDictionaryError(RuntimeError):
    """Raised when the PDF cannot be interpreted as the expected dictionary."""


@dataclass(frozen=True, slots=True)
class ExtractedPdf:
    lines: list[str]
    candidate_line_indexes: set[int]
    page_count: int


def _is_bold(font_name: object) -> bool:
    return "bold" in str(font_name).casefold()


def bold_prefix(line: dict[str, Any]) -> str:
    """Return the initial run of bold characters from a pdfplumber text line."""

    result: list[str] = []
    started = False
    for character in line.get("chars", []):
        text = str(character.get("text", ""))
        if not started and text.isspace():
            continue
        if not _is_bold(character.get("fontname")):
            break
        started = True
        result.append(text)
    return compact_spaces("".join(result))


def is_article_start(line: dict[str, Any]) -> bool:
    """Whether a styled PDF line can begin a dictionary article."""

    prefix = clean_term(bold_prefix(line))
    return bool(prefix) and is_heading_term(prefix)


def extract_pdf(
    input_path: Path,
    *,
    first_page: int = DEFAULT_FIRST_PAGE,
    last_page: int = DEFAULT_LAST_PAGE,
) -> ExtractedPdf:
    """Extract dictionary lines and style-backed article boundaries from PDF."""

    if first_page < 1 or last_page < first_page:
        raise PdfDictionaryError("Invalid inclusive PDF page range")

    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - depends on local tooling
        raise PdfDictionaryError(
            "pdfplumber is required; run `poetry install --with dev`"
        ) from exc

    lines: list[str] = []
    candidate_line_indexes: set[int] = set()
    try:
        with pdfplumber.open(input_path) as document:
            page_count = len(document.pages)
            if last_page > page_count:
                raise PdfDictionaryError(
                    f"Requested page {last_page}, but PDF has only {page_count} pages"
                )
            for page_number in range(first_page, last_page + 1):
                page = document.pages[page_number - 1]
                for line in page.extract_text_lines(return_chars=True):
                    text = str(line.get("text", ""))
                    if is_article_start(line):
                        candidate_line_indexes.add(len(lines))
                    lines.append(text)
                # Prevent heading lookahead and word joining across page
                # boundaries while keeping article bodies contiguous.
                lines.append("")
    except OSError as exc:
        raise PdfDictionaryError(f"Cannot read PDF file: {input_path}") from exc

    return ExtractedPdf(lines, candidate_line_indexes, page_count)


def convert_pdf(
    input_path: Path,
    *,
    first_page: int = DEFAULT_FIRST_PAGE,
    last_page: int = DEFAULT_LAST_PAGE,
) -> dict[str, Any]:
    extracted = extract_pdf(
        input_path,
        first_page=first_page,
        last_page=last_page,
    )
    payload = convert_source_lines(
        extracted.lines,
        source_file=input_path.name,
        candidate_line_indexes=extracted.candidate_line_indexes,
    )
    payload["stats"].update(
        {
            "pdf_page_count": extracted.page_count,
            "parsed_first_page": first_page,
            "parsed_last_page": last_page,
            "styled_heading_candidates": len(extracted.candidate_line_indexes),
        }
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Source PDF dictionary")
    parser.add_argument("output", type=Path, help="Destination JSON file")
    parser.add_argument("--first-page", type=int, default=DEFAULT_FIRST_PAGE)
    parser.add_argument("--last-page", type=int, default=DEFAULT_LAST_PAGE)
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON instead of readable two-space indentation",
    )
    args = parser.parse_args()

    try:
        payload = convert_pdf(
            args.input,
            first_page=args.first_page,
            last_page=args.last_page,
        )
    except PdfDictionaryError as exc:
        parser.error(str(exc))
    args.output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=None if args.compact else 2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {payload['entry_count']} entries to {args.output} "
        f"({payload['stats']['flagged_entry_count']} flagged for review)."
    )


if __name__ == "__main__":
    main()
