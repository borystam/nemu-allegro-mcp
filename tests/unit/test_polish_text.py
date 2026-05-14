"""Polish-text utility tests."""

from __future__ import annotations

import pytest

from allegro_mcp.utils.polish_text import (
    fold_diacritics,
    lightweight_stem,
    looks_like_ean,
    tokenise,
)


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        ("ąćęłńóśźż", "acelnoszz"),
        ("ŁÓDŹ", "LODZ"),
        ("Mateusz Łuczak", "Mateusz Luczak"),
        ("no change", "no change"),
    ],
)
def test_fold_diacritics(input_text: str, expected: str) -> None:
    assert fold_diacritics(input_text) == expected


def test_lightweight_stem_handles_common_suffixes() -> None:
    assert lightweight_stem("rowery") == "rower"
    assert lightweight_stem("rowerami") == "rower"
    assert lightweight_stem("dom") == "dom"


def test_tokenise_splits_on_non_word() -> None:
    assert tokenise("Apple iPhone 15, Pro Max!") == [
        "apple",
        "iphone",
        "15",
        "pro",
        "max",
    ]


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("5901234123457", True),
        ("12345678", True),
        ("123-45678", True),
        ("12345 67890123", True),
        ("not an ean", False),
        ("12345", False),
    ],
)
def test_looks_like_ean(phrase: str, expected: bool) -> None:
    assert looks_like_ean(phrase) is expected
