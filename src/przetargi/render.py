"""Generowanie statycznej strony (HTML + kanały Atom) z bazy ogłoszeń."""

from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Iterable

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .config import REPO_ROOT, Category, Settings
from .models import Tender, today
from .store import TenderStore
from .text import excerpt, normalize

log = logging.getLogger(__name__)

TEMPLATE_DIR = REPO_ROOT / "site" / "templates"
ASSET_DIR = REPO_ROOT / "site" / "assets"
DEFAULT_OUTPUT = REPO_ROOT / "public"
REPO_URL = "https://github.com/ClaudePlos/przetargi24"

MONTHS_PL = (
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
)


def format_value(value: float | None, currency: str) -> str:
    """1234567.0 -> '1 234 568 PLN'. Grosze przy takich kwotach nic nie wnoszą.

    Rozdzielamy tysiące spacją nierozdzielającą (U+00A0), żeby kwota nie
    łamała się na końcu wiersza — tak jak każe polska typografia.
    """
    if not value:
        return ""
    amount = f"{round(value):,}".replace(",", "\u00a0")
    return f"{amount}\u00a0{currency or 'PLN'}"


def human_datetime(iso: str) -> str:
    """'2026-08-31T05:12:00+00:00' -> '31 sierpnia 2026, 05:12 UTC'."""
    if not iso:
        return "jeszcze nie uruchomiono"
    try:
        moment = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return f"{moment.day} {MONTHS_PL[moment.month - 1]} {moment.year}, {moment:%H:%M} UTC"


def to_view(tender: Tender, reference: dt.date, source_labels: dict[str, str]) -> dict[str, Any]:
    """Zamienia model na słownik z polami gotowymi dla szablonu.

    Szablony dostają wyłącznie dane — dzięki temu `tender.is_new` w Jinja2
    nie może przypadkiem odwołać się do metody (która zawsze jest prawdziwa).
    """
    data = tender.to_dict()
    days_left = tender.days_left(reference)
    data.update(
        {
            "summary": tender.summary,
            "is_new": tender.is_new(reference),
            "is_open": tender.is_open(reference),
            "days_left": days_left,
            "value_human": format_value(tender.value, tender.currency),
            "source_label": source_labels.get(tender.source, tender.source.upper()),
            "kind_label": tender.kind_label,
            "search_blob": normalize(
                " ".join(
                    part
                    for part in (
                        tender.title, tender.description, tender.buyer,
                        tender.location, " ".join(tender.cpv), tender.native_id,
                    )
                    if part
                )
            ),
            "updated_iso": f"{tender.last_seen or tender.first_seen or reference.isoformat()}"
            "T00:00:00Z",
            "feed_summary": _feed_summary(tender, days_left),
        }
    )
    return data


def _feed_summary(tender: Tender, days_left: int | None) -> str:
    """Zwięzły opis wpisu do czytnika RSS — najważniejsze fakty w jednym akapicie."""
    parts = []
    if tender.buyer:
        parts.append(f"Zamawiający: {tender.buyer}.")
    if tender.deadline:
        suffix = f" (za {days_left} dni)" if days_left is not None and days_left >= 0 else ""
        parts.append(f"Termin składania ofert: {tender.deadline}{suffix}.")
    if tender.value:
        parts.append(f"Wartość: {format_value(tender.value, tender.currency)}.")
    if tender.cpv:
        parts.append(f"CPV: {', '.join(tender.cpv[:4])}.")
    if tender.description:
        parts.append(excerpt(tender.description, 400))
    return " ".join(parts) or tender.title


class SiteRenderer:
    """Buduje komplet plików strony do katalogu wyjściowego."""

    def __init__(
        self,
        settings: Settings,
        categories: list[Category],
        output: Path | None = None,
        template_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.categories = categories
        self.output = output or DEFAULT_OUTPUT
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"], default_for_string=True),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, store: TenderStore, status: dict[str, Any] | None = None) -> list[Path]:
        status = status or {}
        reference = today()
        source_labels = {
            str(entry.get("key")): str(entry.get("label") or entry.get("key"))
            for entry in status.get("sources", [])
        }

        views = [to_view(t, reference, source_labels) for t in store.sorted()]
        categories_by_slug = {c.slug: {"slug": c.slug, "title": c.title} for c in self.categories}
        site = dict(self.settings.site)
        site.setdefault("title", "Przetargi24")
        site.setdefault("description", "")

        base = {
            "site": site,
            "categories": [
                {"slug": c.slug, "title": c.title, "name": c.name, "description": c.description}
                for c in self.categories
            ],
            "categories_by_slug": categories_by_slug,
            "sources": status.get("sources", []),
            # Do filtra trafiają wyłącznie źródła, z których coś naprawdę mamy —
            # pusta pozycja w liście rozwijanej tylko myliłaby czytelnika.
            "filter_sources": _filter_sources(views, source_labels),
            "updated_at_human": human_datetime(str(status.get("updated_at") or store.updated_at)),
            "updated_at_iso": _atom_timestamp(status.get("updated_at") or store.updated_at),
            "repo_url": REPO_URL,
        }

        self._reset_output()
        written: list[Path] = []

        # Strona główna — wszystkie kategorie razem.
        written.append(
            self._page(
                "index.html",
                "list.html",
                base,
                rel="",
                page="index",
                heading="Wszystkie przetargi",
                intro=site.get("tagline") or site.get("description", ""),
                tenders=views,
                stats=_stats(views),
                show_category_filter=True,
                feed_url="feed.xml",
            )
        )
        written.append(self._feed("feed.xml", base, views, "Wszystkie przetargi", "", ""))

        # Podstrona i kanał dla każdej kategorii.
        category_stats = []
        for category in self.categories:
            subset = [v for v in views if category.slug in v["categories"]]
            written.append(
                self._page(
                    f"kategoria/{category.slug}.html",
                    "list.html",
                    base,
                    rel="../",
                    page=category.slug,
                    heading=category.title,
                    intro=category.description or f"Przetargi z kategorii {category.name}.",
                    tenders=subset,
                    stats=_stats(subset),
                    show_category_filter=False,
                    feed_url=f"kategoria/{category.slug}.xml",
                )
            )
            written.append(
                self._feed(
                    f"kategoria/{category.slug}.xml",
                    base,
                    subset,
                    category.title,
                    category.description,
                    f"kategoria/{category.slug}.html",
                )
            )
            category_stats.append(
                {
                    "slug": category.slug,
                    "title": category.title,
                    "count": len(subset),
                    "new_today": sum(1 for v in subset if v["is_new"]),
                }
            )

        # Strona diagnostyczna: co odpowiedziało, a co nie.
        written.append(
            self._page(
                "zrodla.html",
                "zrodla.html",
                base,
                rel="",
                page="zrodla",
                category_stats=category_stats,
                run=status.get("run") or {"added": 0, "updated": 0, "merged": 0, "removed": 0},
            )
        )

        written.extend(self._copy_assets())
        written.extend(self._copy_data(store, status))
        log.info("Wygenerowano %s plików w %s", len(written), self.output)
        return written

    # -- pomocnicze --------------------------------------------------------

    def _reset_output(self) -> None:
        if self.output.exists():
            shutil.rmtree(self.output)
        (self.output / "kategoria").mkdir(parents=True, exist_ok=True)

    def _page(self, target: str, template: str, base: dict[str, Any], **context: Any) -> Path:
        html = self.env.get_template(template).render(**base, **context)
        return self._write(target, html)

    def _feed(
        self,
        target: str,
        base: dict[str, Any],
        views: list[dict[str, Any]],
        heading: str,
        intro: str,
        page: str,
    ) -> Path:
        site_url = self.settings.site_url or REPO_URL
        # Kanał ma sens tylko dla świeżych wpisów — 60 pozycji to typowy limit czytników.
        xml = self.env.get_template("feed.xml").render(
            **base,
            heading=heading,
            intro=intro or base["site"].get("description", ""),
            tenders=views[:60],
            feed_id=f"{site_url}/{target}",
            self_url=f"{site_url}/{target}",
            page_url=f"{site_url}/{page}" if page else site_url,
        )
        return self._write(target, xml)

    def _write(self, target: str, content: str) -> Path:
        path = self.output / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _copy_assets(self) -> list[Path]:
        destination = self.output / "assets"
        destination.mkdir(parents=True, exist_ok=True)
        written = []
        for asset in sorted(ASSET_DIR.glob("*")):
            if asset.is_file():
                shutil.copy2(asset, destination / asset.name)
                written.append(destination / asset.name)
        # Bez tego GitHub Pages przepuściłoby katalogi przez Jekylla.
        (self.output / ".nojekyll").write_text("", encoding="utf-8")
        return written

    def _copy_data(self, store: TenderStore, status: dict[str, Any]) -> list[Path]:
        """Udostępnia surowe dane pod /dane/ — do własnych integracji."""
        written = []
        payload = {
            "updated_at": store.updated_at,
            "count": len(store.tenders),
            "tenders": [t.to_dict() for t in store.sorted()],
        }
        written.append(self._write("dane/tenders.json", json.dumps(payload, ensure_ascii=False)))
        written.append(self._write("dane/status.json", json.dumps(status, ensure_ascii=False)))
        return written


def _filter_sources(
    views: list[dict[str, Any]], labels: dict[str, str]
) -> list[dict[str, str]]:
    """Źródła obecne w danych, posortowane wg etykiety."""
    keys = sorted({v["source"] for v in views if v.get("source")})
    return [{"key": key, "label": labels.get(key, key.upper())} for key in keys]


def _stats(views: Iterable[dict[str, Any]]) -> dict[str, int]:
    items = list(views)
    return {
        "total": len(items),
        "new_today": sum(1 for v in items if v["is_new"]),
        "open": sum(1 for v in items if v["is_open"]),
        "plans": sum(1 for v in items if v["kind"] == "plan"),
    }


def _atom_timestamp(value: Any) -> str:
    """Atom wymaga pełnego znacznika RFC 3339."""
    text = str(value or "")
    if not text:
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.replace(microsecond=0).isoformat()
