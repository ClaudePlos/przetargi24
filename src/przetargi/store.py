"""Trwałe przechowywanie ogłoszeń w repozytorium (data/tenders.json)."""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import REPO_ROOT
from .models import Tender, today
from .text import normalize

log = logging.getLogger(__name__)

DEFAULT_DATA_DIR = REPO_ROOT / "data"
STORE_VERSION = 1

# Pola nadpisywane danymi ze źródła przy każdej aktualizacji. `first_seen`
# celowo nie jest na liście — data pierwszego zauważenia ma być stała.
REFRESHABLE = (
    "title", "url", "description", "buyer", "location", "cpv", "kind",
    "publication_date", "deadline", "value", "currency", "categories", "scores",
)


@dataclass
class UpdateReport:
    """Podsumowanie jednego przebiegu — trafia do logu i do GitHub Actions."""

    added: int = 0
    updated: int = 0
    removed: int = 0
    merged: int = 0
    total: int = 0
    per_category: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "merged": self.merged,
            "total": self.total,
            "per_category": self.per_category,
        }


class TenderStore:
    """Kolekcja ogłoszeń zapisana jako jeden plik JSON, wersjonowana w gicie."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (DEFAULT_DATA_DIR / "tenders.json")
        self.tenders: dict[str, Tender] = {}
        self.updated_at: str = ""

    # -- wejście/wyjście ---------------------------------------------------

    def load(self) -> "TenderStore":
        if not self.path.is_file():
            log.info("Brak %s — zaczynam od pustej bazy", self.path)
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Nie udało się wczytać %s (%s) — zaczynam od pustej bazy", self.path, exc)
            return self

        self.updated_at = str(raw.get("updated_at") or "")
        for item in raw.get("tenders") or []:
            if not isinstance(item, dict):
                continue
            tender = Tender.from_dict(item)
            if tender.id:
                self.tenders[tender.id] = tender
        log.info("Wczytano %s ogłoszeń z %s", len(self.tenders), self.path)
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STORE_VERSION,
            "updated_at": self.updated_at or _now(),
            "count": len(self.tenders),
            "tenders": [t.to_dict() for t in self.sorted()],
        }
        # sort_keys + stały wcięcie: diff w gicie pokazuje realne zmiany,
        # a nie przetasowanie kluczy.
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        log.info("Zapisano %s ogłoszeń do %s", len(self.tenders), self.path)

    # -- odczyt ------------------------------------------------------------

    def sorted(self) -> list[Tender]:
        """Najnowsze publikacje na początku listy."""
        return sorted(self.tenders.values(), key=lambda t: t.sort_key(), reverse=True)

    def by_category(self, slug: str) -> list[Tender]:
        return [t for t in self.sorted() if slug in t.categories]

    # -- aktualizacja ------------------------------------------------------

    def merge(self, incoming: Iterable[Tender], reference: dt.date | None = None) -> UpdateReport:
        """Wprowadza świeże ogłoszenia: dokłada nowe, odświeża znane."""
        stamp = (reference or today()).isoformat()
        report = UpdateReport()

        for tender in incoming:
            existing = self.tenders.get(tender.id)
            if existing is None:
                tender.first_seen = tender.first_seen or stamp
                tender.last_seen = stamp
                self.tenders[tender.id] = tender
                report.added += 1
                continue

            changed = False
            for name in REFRESHABLE:
                new_value = getattr(tender, name)
                # Puste pole ze źródła nie kasuje danych, które już mamy.
                if new_value in (None, "", [], {}):
                    continue
                if getattr(existing, name) != new_value:
                    setattr(existing, name, new_value)
                    changed = True
            existing.last_seen = stamp
            if changed:
                report.updated += 1

        report.merged = self.deduplicate()
        report.total = len(self.tenders)
        return report

    def deduplicate(self) -> int:
        """Skleja to samo zamówienie ogłoszone w kilku źródłach.

        Klucz to tytuł + zamawiający + rok publikacji, więc coroczne
        powtórki tego samego przetargu zostają osobnymi wpisami.
        """
        groups: dict[tuple[str, str, str], list[Tender]] = {}
        for tender in self.tenders.values():
            if not tender.buyer:
                continue  # bez zamawiającego sam tytuł to za słaba przesłanka
            key = (
                normalize(tender.title)[:120],
                normalize(tender.buyer)[:80],
                (tender.publication_date or "")[:4],
            )
            groups.setdefault(key, []).append(tender)

        merged = 0
        for duplicates in groups.values():
            if len(duplicates) < 2:
                continue
            primary = max(duplicates, key=_completeness)
            for other in duplicates:
                if other.id == primary.id:
                    continue
                primary.extra_links.append(
                    {"label": f"Ta sama sprawa w: {other.source.upper()}", "url": other.url}
                )
                primary.first_seen = min(
                    filter(None, [primary.first_seen, other.first_seen]), default=primary.first_seen
                )
                self.tenders.pop(other.id, None)
                merged += 1
        return merged

    def prune(self, retention_days: int, reference: dt.date | None = None) -> int:
        """Usuwa wpisy, których termin (lub publikacja) dawno minęły."""
        cutoff = (reference or today()) - dt.timedelta(days=max(1, retention_days))
        stale = [tid for tid, t in self.tenders.items() if _effective_date(t) < cutoff.isoformat()]
        for tid in stale:
            del self.tenders[tid]
        if stale:
            log.info("Usunięto %s przeterminowanych wpisów (starsze niż %s)", len(stale), cutoff)
        return len(stale)

    def touch(self) -> None:
        self.updated_at = _now()


def _effective_date(tender: Tender) -> str:
    """Data, względem której liczymy przeterminowanie wpisu."""
    return tender.deadline or tender.publication_date or tender.first_seen or "9999-12-31"


def _completeness(tender: Tender) -> tuple:
    """Im więcej wypełnionych pól, tym lepszy kandydat na wpis główny."""
    return (
        bool(tender.description),
        bool(tender.deadline),
        bool(tender.value),
        len(tender.cpv),
        len(tender.url),
    )


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def write_status(
    path: Path,
    sources: list[dict[str, Any]],
    report: UpdateReport,
    categories: list[dict[str, Any]],
) -> None:
    """Zapisuje stan ostatniego przebiegu — pokazywany na stronie."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _now(),
        "sources": sources,
        "run": report.to_dict(),
        "categories": categories,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
