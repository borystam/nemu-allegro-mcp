"""Polish text utilities: diacritic folding and lightweight stemming."""

from __future__ import annotations

import re
import unicodedata

_DIACRITIC_MAP = str.maketrans(
    {
        "ą": "a",
        "ć": "c",
        "ę": "e",
        "ł": "l",
        "ń": "n",
        "ó": "o",
        "ś": "s",
        "ź": "z",
        "ż": "z",
        "Ą": "A",
        "Ć": "C",
        "Ę": "E",
        "Ł": "L",
        "Ń": "N",
        "Ó": "O",
        "Ś": "S",
        "Ź": "Z",
        "Ż": "Z",
    }
)

_COMMON_SUFFIXES = (
    "ami",
    "ach",
    "om",
    "owi",
    "ego",
    "emu",
    "ich",
    "imi",
    "ych",
    "ymi",
    "iem",
    "em",
    "ie",
    "iu",
    "ia",
    "y",
    "i",
    "a",
    "e",
    "u",
    "o",
)


def fold_diacritics(text: str) -> str:
    """Strip Polish diacritics, preserving everything else.

    Useful for fallback search when users type without diacritics or when the
    upstream phrase has been transliterated.
    """
    folded = text.translate(_DIACRITIC_MAP)
    # Belt and braces: also normalise any remaining combining characters.
    normalised = unicodedata.normalize("NFD", folded)
    return "".join(ch for ch in normalised if not unicodedata.combining(ch))


def lightweight_stem(token: str) -> str:
    """Strip the longest matching common Polish suffix.

    This is deliberately crude; it is good enough to broaden a search phrase
    when the initial query returns few results.
    """
    lowered = token.lower()
    for suffix in _COMMON_SUFFIXES:
        if len(lowered) > len(suffix) + 2 and lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def tokenise(phrase: str) -> list[str]:
    """Break `phrase` into alphanumeric tokens, lowercased."""
    return [token for token in re.split(r"[^\w]+", phrase.lower(), flags=re.UNICODE) if token]


_EAN_RE = re.compile(r"^\d{8}$|^\d{12,14}$")


def looks_like_ean(phrase: str) -> bool:
    """Return True if `phrase` matches EAN-8, UPC-12, EAN-13 or GTIN-14."""
    stripped = phrase.strip().replace(" ", "").replace("-", "")
    return bool(_EAN_RE.fullmatch(stripped))
