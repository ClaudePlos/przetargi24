"""Model pojedynczego ogłoszenia oraz pomocnicze funkcje na datach."""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .text import collapse_whitespace, excerpt

# Rodzaje wpisów. `PLAN` to pozycja z planu postępowań — przetarg, który
# dopiero zostanie ogłoszony; to on odpowiada za "co się niedługo wydarzy".
KIND_NOTICE = "ogloszenie"
KIND_PLAN = "plan"

KIND_LABELS = {
    KIND_NOTICE: "Ogłoszenie",
    KIND_PLAN: "Plan postępowań",
}


def today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def parse_date(value: Any) -> str | None:
    """Sprowadza datę z dowolnego źródła do formatu ISO (RRRR-MM-DD).

    Źródła zwracają daty w kilku formatach (ISO z offsetem, ISO ze strefą 'Z',
    sam dzień, czasem timestamp), a niektóre pola bywają listą — bierzemy
    wtedy pierwszy element.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            parsed = parse_date(item)
            if parsed:
                return parsed
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(float(value), dt.timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None

    # Najczęstszy przypadek: pełny znacznik ISO, ewentualnie z 'Z' na końcu.
    candidate = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        return dt.datetime.fromisoformat(candidate).date().isoformat()
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text[: len(fmt) + 4], fmt).date().isoformat()
        except ValueError:
            continue

    # Ostatnia próba: wyłuskaj RRRR-MM-DD z dłuższego napisu.
    if len(text) >= 10:
        try:
            return dt.date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return None
    return None


def days_until(iso_date: str | None, reference: dt.date | None = None) -> int | None:
    """Ile dni zostało do podanej daty (ujemnie, gdy termin minął)."""
    if not iso_date:
        return None
    try:
        target = dt.date.fromisoformat(iso_date)
    except ValueError:
        return None
    return (target - (reference or today())).days


@dataclass
class Tender:
    """Jedno ogłoszenie lub pozycja planu postępowań."""

    id: str
    source: str
    native_id: str
    title: str
    url: str = ""
    description: str = ""
    buyer: str = ""
    location: str = ""
    cpv: list[str] = field(default_factory=list)
    kind: str = KIND_NOTICE
    publication_date: str | None = None
    deadline: str | None = None
    value: float | None = None
    currency: str = ""
    extra_links: list[dict[str, str]] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""

    # ---- pola wyliczane, używane przez szablony strony -------------------

    @property
    def summary(self) -> str:
        return excerpt(self.description or self.title)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    def days_left(self, reference: dt.date | None = None) -> int | None:
        return days_until(self.deadline, reference)

    def is_open(self, reference: dt.date | None = None) -> bool:
        """Czy nadal można złożyć ofertę (brak terminu traktujemy jak otwarty)."""
        left = self.days_left(reference)
        return True if left is None else left >= 0

    def is_new(self, reference: dt.date | None = None) -> bool:
        """Czy wpis pojawił się w portalu podczas ostatniej aktualizacji."""
        return bool(self.first_seen) and self.first_seen == (reference or today()).isoformat()

    def sort_key(self) -> tuple:
        """Najnowsze publikacje na górze; brak daty ląduje na końcu."""
        return (self.publication_date or "", self.first_seen or "", self.id)

    # ---- serializacja ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tender":
        known = {f.name for f in dataclasses.fields(cls)}
        payload = {k: v for k, v in data.items() if k in known}
        payload.setdefault("id", "")
        payload.setdefault("source", "")
        payload.setdefault("native_id", "")
        payload.setdefault("title", "")
        return cls(**payload)

    def normalized(self) -> "Tender":
        """Czyści białe znaki i odsiewa puste wartości po stronie źródła."""
        self.title = collapse_whitespace(self.title) or "(bez tytułu)"
        self.description = collapse_whitespace(self.description)
        self.buyer = collapse_whitespace(self.buyer)
        self.location = collapse_whitespace(self.location)
        self.cpv = [str(c).strip() for c in self.cpv if str(c).strip()]
        self.extra_links = [
            link for link in self.extra_links if link.get("url") and link.get("label")
        ]
        return self

    def search_text(self) -> str:
        """Materiał do dopasowania kategorii i wyszukiwarki na stronie."""
        return " ".join(
            part for part in (self.title, self.description, self.buyer, " ".join(self.cpv)) if part
        )
