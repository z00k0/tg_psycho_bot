#!/usr/bin/env python3
"""Convert the extracted Russian psychology dictionary text to JSON.

The source is a text export of a paginated Word document.  Entry headings are
uppercase and separated from their definitions by a dash outside parentheses.
The converter also removes page-number-only lines and joins words split across
line/page boundaries.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path


DASHES = "-–—"
RUSSIAN_LETTERS = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
LETTER_RANK = {letter: index for index, letter in enumerate(RUSSIAN_LETTERS)}
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")
SPACE_RE = re.compile(r"\s+")
PAREN_RE = re.compile(r"\([^()]*\)")
CYRILLIC_RE = re.compile(r"[А-ЯЁа-яё]")
UPPER_CYRILLIC_RE = re.compile(r"[А-ЯЁ]")
LOWER_CYRILLIC_RE = re.compile(r"[а-яё]")
DIRECT_REFERENCE_RE = re.compile(
    r"^см\.?\s+(.+?)(?:[.!?](?:\s|$)|$)", re.IGNORECASE
)
TRAILING_META_RE = re.compile(
    r"\s*(\((?:\d{3,4}\s*[–—-]\s*\d{2,4}|"
    r"[^()]*(?:\bот\b|букв\.?|англ\.?|греч\.?|лат\.?|нем\.?|франц\.?)"
    r"[^()]*)\))\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    line_index: int
    heading_end_index: int
    heading: str
    term: str


def compact_spaces(text: str) -> str:
    return SPACE_RE.sub(" ", text).strip()


def normalize_source_line(line: str) -> str:
    return (
        unicodedata.normalize("NFC", line)
        .replace("\u00ad", "")
        .replace("\u00a0", " ")
        .strip()
    )


def find_definition_dash(text: str) -> int | None:
    """Return the heading/definition dash outside parentheses."""
    depth = 0
    fallback: int | None = None
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char in DASHES and depth == 0:
            before = text[index - 1] if index else ""
            after = text[index + 1] if index + 1 < len(text) else ""
            # A separator normally has whitespace on at least one side.  This
            # avoids treating internal hyphens as a heading boundary.
            if before.isspace() or after.isspace():
                if fallback is None:
                    fallback = index
                remainder = text[index + 1 :].lstrip()
                # A spaced dash can also join surnames inside an uppercase
                # heading (e.g. "АУБЕРТА – ФЕРСТЕРА ФЕНОМЕН"). Prefer the dash
                # followed by ordinary definition prose.
                first_cyrillic = CYRILLIC_RE.search(remainder[:20])
                if (
                    remainder[:1].isdigit()
                    or (first_cyrillic and first_cyrillic.group(0).islower())
                ):
                    return index
    return fallback


def split_heading(text: str) -> tuple[str, str] | None:
    dash_index = find_definition_dash(text)
    if dash_index is None:
        return None
    heading = compact_spaces(text[:dash_index])
    definition = compact_spaces(text[dash_index + 1 :])
    return heading, definition


def clean_term(heading: str) -> str:
    """Remove trailing etymology or lifespan while retaining term qualifiers."""
    term = heading.strip()
    while True:
        match = TRAILING_META_RE.search(term)
        if not match:
            break
        term = term[: match.start()].rstrip()
    return compact_spaces(term).strip(" ,:;")


def is_heading_term(term: str) -> bool:
    if not (2 <= len(term) <= 160):
        return False
    visible = PAREN_RE.sub("", term)
    letters = CYRILLIC_RE.findall(visible)
    if len(letters) < 2:
        return False
    if LOWER_CYRILLIC_RE.search(visible):
        return False
    # Headings are mostly Russian uppercase text. Latin capitals and digits are
    # allowed for abbreviations, years, and named tests.
    allowed = re.sub(r"[А-ЯЁA-Z0-9\s.,:;/'\"«»()№+&–—-]", "", visible)
    return not allowed


def candidate_at(lines: list[str], index: int) -> Candidate | None:
    if not lines[index]:
        return None
    if re.fullmatch(r"[А-ЯЁ]", lines[index]):
        # Alphabet section marker, not part of the following person's name.
        return None
    combined = lines[index]
    # Some person names and parenthetical qualifiers wrap to the next source
    # line. Never bridge a blank line here: blanks are useful boundary evidence.
    for lookahead in range(3):
        split = split_heading(combined)
        if split:
            heading, _ = split
            term = clean_term(heading)
            if is_heading_term(term):
                return Candidate(index, index + lookahead, heading, term)
            return None
        if len(combined) > 500:
            break
        next_index = index + lookahead + 1
        if next_index >= len(lines) or not lines[next_index]:
            break
        next_line = lines[next_index]
        if combined.endswith("-"):
            combined = combined[:-1] + next_line
        else:
            last_token = combined.rsplit(" ", 1)[-1]
            first_token = next_line.split(" ", 1)[0]
            split_uppercase_word = (
                combined == combined.upper()
                and next_line[:1].isupper()
                and len(last_token) <= 4
                and len(first_token.rstrip(DASHES)) <= 5
            )
            separator = "" if split_uppercase_word else " "
            combined = f"{combined}{separator}{next_line}"
    return None


def remove_singleton_letter_jumps(candidates: list[Candidate]) -> list[Candidate]:
    """Drop obvious continuation fragments that break dictionary ordering."""
    if len(candidates) < 3:
        return candidates
    kept: list[Candidate] = []
    for index, candidate in enumerate(candidates):
        if index == 0 or index == len(candidates) - 1:
            kept.append(candidate)
            continue
        prev_letter = dictionary_letter(candidates[index - 1].term)
        this_letter = dictionary_letter(candidate.term)
        next_letter = dictionary_letter(candidates[index + 1].term)
        prev_rank = LETTER_RANK.get(prev_letter)
        this_rank = LETTER_RANK.get(this_letter)
        next_rank = LETTER_RANK.get(next_letter)
        is_jump = (
            None not in (prev_rank, this_rank, next_rank)
            and prev_rank <= next_rank
            and this_rank > next_rank
        )
        if not is_jump:
            kept.append(candidate)
    return kept


def join_article_lines(lines: list[str]) -> str:
    parts: list[str] = []
    for line in lines:
        if not line:
            continue
        if re.fullmatch(r"[А-ЯЁ]", line):
            continue
        if parts and parts[-1].endswith("-") and line[:1].isalpha():
            parts[-1] = parts[-1][:-1] + line
            continue
        if parts and parts[-1] == parts[-1].upper() and line[:1].isupper():
            last_token = parts[-1].rsplit(" ", 1)[-1]
            first_token = line.split(" ", 1)[0]
            if len(last_token) <= 4 and len(first_token.rstrip(DASHES)) <= 5:
                parts[-1] += line
                continue
        parts.append(line)
    return compact_spaces(" ".join(parts))


def normalized_search_term(term: str) -> str:
    value = unicodedata.normalize("NFC", term).upper().replace("Ё", "Е")
    value = re.sub(r"[^А-ЯA-Z0-9]+", " ", value)
    return compact_spaces(value)


def dictionary_letter(term: str) -> str:
    match = UPPER_CYRILLIC_RE.search(term.upper())
    return match.group(0).replace("Ё", "Е") if match else "#"


def search_variants(term: str) -> list[str]:
    variants = [term]
    if "," in term:
        pieces = [compact_spaces(piece) for piece in term.split(",")]
        if all(piece and is_heading_term(piece) for piece in pieces):
            variants.extend(pieces)
    seen: set[str] = set()
    result: list[str] = []
    for variant in variants:
        normalized = normalized_search_term(variant)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def quality_flags(term: str, definition: str) -> list[str]:
    flags: list[str] = []
    letter_count = len(CYRILLIC_RE.findall(term))
    if letter_count <= 3:
        flags.append("short_heading")
    if len(definition) < 20:
        flags.append("short_definition")
    if definition and definition[-1] not in ".!?»)]":
        flags.append("possibly_truncated")
    if "�" in term or "�" in definition:
        flags.append("replacement_character")
    return flags


def convert(input_path: Path) -> dict:
    raw = input_path.read_text(encoding="utf-8-sig")
    source_lines = raw.splitlines()
    lines: list[str] = []
    removed_page_numbers = 0
    for raw_line in source_lines:
        line = normalize_source_line(raw_line)
        if PAGE_NUMBER_RE.fullmatch(line):
            removed_page_numbers += 1
            lines.append("")
        else:
            lines.append(line)

    candidates: list[Candidate] = []
    index = 0
    while index < len(lines):
        candidate = candidate_at(lines, index)
        if candidate is None:
            index += 1
            continue
        candidates.append(candidate)
        # Do not emit a second entry from a wrapped heading's continuation.
        index = candidate.heading_end_index + 1
    candidates = remove_singleton_letter_jumps(candidates)

    entries: list[dict] = []
    for position, candidate in enumerate(candidates):
        end = (
            candidates[position + 1].line_index
            if position + 1 < len(candidates)
            else len(lines)
        )
        article = join_article_lines(lines[candidate.line_index : end])
        split = split_heading(article)
        if not split:
            continue
        heading, definition = split
        term = clean_term(heading)
        direct_reference = DIRECT_REFERENCE_RE.match(definition)
        redirect_to = (
            compact_spaces(direct_reference.group(1)).strip(" .")
            if direct_reference
            else None
        )
        entry = {
            "id": len(entries) + 1,
            "term": term,
            "term_normalized": normalized_search_term(term),
            "search_terms": search_variants(term),
            "letter": dictionary_letter(term),
            "heading": heading,
            "definition": definition,
            "redirect_to": redirect_to,
            "quality_flags": quality_flags(term, definition),
        }
        entries.append(entry)

    duplicate_terms: dict[str, list[int]] = {}
    for entry in entries:
        duplicate_terms.setdefault(entry["term_normalized"], []).append(entry["id"])
    duplicates = {
        term: ids for term, ids in duplicate_terms.items() if len(ids) > 1
    }

    return {
        "schema_version": 1,
        "language": "ru",
        "source_file": input_path.name,
        "generated_on": date.today().isoformat(),
        "entry_count": len(entries),
        "stats": {
            "source_line_count": len(source_lines),
            "removed_page_number_lines": removed_page_numbers,
            "redirect_count": sum(bool(item["redirect_to"]) for item in entries),
            "flagged_entry_count": sum(bool(item["quality_flags"]) for item in entries),
            "duplicate_normalized_terms": duplicates,
        },
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="UTF-8 dictionary text file")
    parser.add_argument("output", type=Path, help="Destination JSON file")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON instead of readable two-space indentation",
    )
    args = parser.parse_args()

    payload = convert(args.input)
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
