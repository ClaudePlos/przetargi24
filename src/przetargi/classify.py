"""Przypisywanie ogłoszeń do kategorii na podstawie kodów CPV i słów kluczowych."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

from .config import Category, Settings
from .models import Tender
from .text import normalize

_CPV_CLEAN = re.compile(r"[^0-9]")


def normalize_cpv(code: str) -> str:
    """'90910000-9' -> '90910000'. Zostawia same cyfry, ucina cyfrę kontrolną."""
    digits = _CPV_CLEAN.sub("", str(code))
    # Pełny kod CPV ma 8 cyfr + cyfra kontrolna po myślniku; gdy myślnik
    # zniknął po drodze, dziewiąta cyfra jest cyfrą kontrolną.
    return digits[:8] if len(digits) > 8 else digits


@lru_cache(maxsize=2048)
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Kompiluje frazę do wyrażenia; gwiazdka zastępuje resztę wyrazu.

    Dopasowanie jest podłańcuchowe, więc krótszy rdzeń łapie polską odmianę:
    'sprzatani' trafia w 'sprzątanie', 'sprzątania' i 'sprzątaniem'.
    Gwiazdka nie przeskakuje spacji, więc 'czyszczeni* kanalizacj*' wymaga
    sąsiadujących wyrazów i nie złapie 'czyszczenie okien oraz kanalizacji'.
    """
    escaped = re.escape(normalize(keyword)).replace(r"\*", r"\w*")
    return re.compile(escaped)


def _matches_any(text: str, keywords: Iterable[str]) -> list[str]:
    return [kw for kw in keywords if _keyword_pattern(kw).search(text)]


def _matches_prefix(codes: Iterable[str], prefixes: Iterable[str]) -> bool:
    """Czy któryś kod CPV zaczyna się od któregoś z podanych przedrostków."""
    normalized = [normalize_cpv(prefix) for prefix in prefixes]
    return any(
        code and prefix and code.startswith(prefix) for code in codes for prefix in normalized
    )


def score_category(tender: Tender, category: Category, settings: Settings) -> int:
    """Liczy punkty trafności ogłoszenia dla jednej kategorii (0 = brak)."""
    text = normalize(tender.search_text())
    if category.exclude_keywords and _matches_any(text, category.exclude_keywords):
        return 0

    codes = [normalize_cpv(code) for code in tender.cpv]
    if category.exclude_cpv and _matches_prefix(codes, category.exclude_cpv):
        # Kod wykluczony dyskwalifikuje ogłoszenie tak samo jak fraza —
        # np. 15700000 (pasza dla zwierząt) mimo trafienia w szeroki dział 15.
        return 0

    cpv_points = int(settings.classify.get("cpv_points", 3))
    keyword_points = int(settings.classify.get("keyword_points", 2))

    prefixes = [normalize_cpv(prefix) for prefix in category.cpv]
    cpv_hits = sum(
        1
        for code in codes
        if code and any(prefix and code.startswith(prefix) for prefix in prefixes)
    )

    keyword_hits = len(_matches_any(text, category.keywords))
    return cpv_hits * cpv_points + keyword_hits * keyword_points


def classify(tender: Tender, categories: Iterable[Category], settings: Settings) -> Tender:
    """Uzupełnia `tender.categories` i `tender.scores`. Modyfikuje obiekt w miejscu."""
    default_min = int(settings.classify.get("default_min_score", 2))
    scores: dict[str, int] = {}
    for category in categories:
        score = score_category(tender, category, settings)
        threshold = category.min_score if category.min_score is not None else default_min
        if score >= threshold:
            scores[category.slug] = score

    # Najtrafniejsza kategoria jako pierwsza — tak też pokazujemy plakietki.
    tender.scores = scores
    tender.categories = [slug for slug, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]
    return tender


def classify_all(
    tenders: Iterable[Tender], categories: Iterable[Category], settings: Settings
) -> list[Tender]:
    """Zwraca tylko te ogłoszenia, które trafiły do co najmniej jednej kategorii."""
    category_list = list(categories)
    matched = []
    for tender in tenders:
        classify(tender, category_list, settings)
        if tender.categories:
            matched.append(tender)
    return matched
