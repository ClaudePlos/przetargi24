"""Normalizacja tekstu na potrzeby wyszukiwania i dopasowywania kategorii."""

from __future__ import annotations

import re
import unicodedata

# Znaki, których unicodedata nie rozkłada na literę + znak diakrytyczny.
_SPECIAL = str.maketrans({"ł": "l", "Ł": "L", "ß": "ss"})

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^0-9a-z]+")


def strip_diacritics(value: str) -> str:
    """Zamienia 'żółć' na 'zolc' — pozwala szukać bez polskich znaków."""
    decomposed = unicodedata.normalize("NFKD", value.translate(_SPECIAL))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(value: str | None) -> str:
    """Tekst do porównań: bez diakrytyków, małymi literami, jedna spacja."""
    if not value:
        return ""
    return _WHITESPACE.sub(" ", strip_diacritics(value).lower()).strip()


def slugify(value: str, fallback: str = "pozycja") -> str:
    """Buduje bezpieczny fragment adresu URL / nazwy pliku."""
    slug = _NON_WORD.sub("-", normalize(value)).strip("-")
    return slug or fallback


def collapse_whitespace(value: str | None) -> str:
    """Skleja wieloliniowy tekst w jeden akapit, zachowując oryginalne znaki."""
    if not value:
        return ""
    return _WHITESPACE.sub(" ", value).strip()


def excerpt(value: str | None, limit: int = 320) -> str:
    """Skraca opis do `limit` znaków, ucinając na granicy słowa."""
    text = collapse_whitespace(value)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-") + "…"
