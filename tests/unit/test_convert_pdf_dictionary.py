from __future__ import annotations

from convert_dictionary import convert_source_lines, normalized_search_term
from convert_pdf_dictionary import bold_prefix, is_article_start


def _line(text: str, *, bold_characters: int) -> dict[str, object]:
    return {
        "text": text,
        "chars": [
            {
                "text": character,
                "fontname": "Arial,Bold" if index < bold_characters else "Arial",
            }
            for index, character in enumerate(text)
        ],
    }


def test_article_start_requires_bold_uppercase_heading() -> None:
    article = _line("АБСТРАКЦИЯ — определение.", bold_characters=10)
    internal_subheading = _line("Формальная А. состоит...", bold_characters=11)
    plain_uppercase = _line("АБУЛИЯ — определение.", bold_characters=0)

    assert bold_prefix(article) == "АБСТРАКЦИЯ"
    assert is_article_start(article)
    assert not is_article_start(internal_subheading)
    assert not is_article_start(plain_uppercase)


def test_structured_candidates_restrict_plain_text_heading_detection() -> None:
    lines = [
        "ЛОЖНЫЙ ТЕРМИН — не должен стать статьёй.",
        "АБУЛИЯ — отсутствие инициативы и побуждений к деятельности.",
    ]

    payload = convert_source_lines(
        lines,
        source_file="dictionary.pdf",
        candidate_line_indexes={1},
    )

    assert payload["source_file"] == "dictionary.pdf"
    assert [entry["term"] for entry in payload["entries"]] == ["АБУЛИЯ"]


def test_search_normalization_preserves_non_ascii_letters() -> None:
    assert normalized_search_term("БЮЛЕР КАРЛ (Bühler)") == "БЮЛЕР КАРЛ BÜHLER"


def test_short_cross_reference_is_not_flagged_as_truncated() -> None:
    payload = convert_source_lines(
        ["АВОКАЛИЯ — См. Амузия."],
        source_file="dictionary.pdf",
        candidate_line_indexes={0},
    )

    assert payload["entries"][0]["redirect_to"] == "Амузия"
    assert payload["entries"][0]["quality_flags"] == []


def test_pdf_style_page_numbers_are_removed_from_article_body() -> None:
    payload = convert_source_lines(
        [
            "АБУЛИЯ — первая часть определения",
            "59.",
            "продолжение определения.",
            "_Б_",
            "_X_",
            "Рис. 6",
        ],
        source_file="dictionary.pdf",
        candidate_line_indexes={0},
    )

    assert payload["entries"][0]["definition"] == (
        "первая часть определения продолжение определения."
    )
    assert payload["stats"]["removed_page_number_lines"] == 1
