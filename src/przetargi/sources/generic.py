"""Uniwersalne źródło JSON konfigurowane w pliku `config/sources.yml`.

Pozwala podpiąć kolejne API z ogłoszeniami bez pisania kodu — wystarczy
opisać adres, sposób stronicowania i mapowanie pól. Dzięki temu poprawka
po zmianie API sprowadza się do edycji YAML-a.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Iterator

from ..models import KIND_NOTICE, Tender, parse_date
from ..text import collapse_whitespace
from .base import (
    FetchContext,
    Source,
    SourceError,
    dig,
    extract_cpv_codes,
    first_text,
    pick_ci,
    to_float,
)

log = logging.getLogger(__name__)

# Klucze, pod którymi API zwykle chowa listę wyników, gdy nie podano `result_path`.
FALLBACK_RESULT_KEYS = ("items", "list", "results", "data", "content", "rows", "elements")

# Pola, które adapter potrafi wypełnić z mapowania w YAML-u.
TEXT_FIELDS = ("title", "description", "buyer", "location", "native_id", "currency")
DATE_FIELDS = ("publication_date", "deadline")


class GenericJsonSource(Source):
    """Źródło opisane słownikiem konfiguracji z `config/sources.yml`."""

    def __init__(self, key: str, config: dict[str, Any]) -> None:
        self.key = key
        self.config = config or {}
        self.label = str(self.config.get("label") or key)
        self.homepage = str(self.config.get("homepage") or "")
        self.enabled = bool(self.config.get("enabled", True))
        self.kind = str(self.config.get("kind") or KIND_NOTICE)
        # Rodzaj wpisu może wynikać z pola w rekordzie — w BZP ogłoszenia
        # i plany postępowań wracają z tego samego adresu, rozróżnia je
        # dopiero `noticeType`.
        self.kind_field = str(self.config.get("kind_field") or "")
        self.kind_map: dict[str, str] = {
            str(k): str(v) for k, v in (self.config.get("kind_map") or {}).items()
        }
        self.skip_kinds = {str(v) for v in (self.config.get("skip_kinds") or [])}

        self.url = str(self.config.get("url") or "")
        if not self.url:
            raise SourceError(f"Źródło '{key}': brak wymaganego pola 'url'")
        self.method = str(self.config.get("method", "GET")).upper()
        self.result_path = str(self.config.get("result_path") or "")
        self.field_map: dict[str, Any] = self.config.get("fields") or {}
        self.detail_url = str(self.config.get("detail_url") or "")
        self.page_size = int(self.config.get("page_size", 50))
        # Nadpisanie globalnego `fetch.max_pages` — źródło z małą stroną
        # potrzebuje ich więcej, żeby objąć ten sam zakres dni.
        self.max_pages = int(self.config["max_pages"]) if "max_pages" in self.config else None
        self.first_page = int(self.config.get("first_page", 1))
        self.date_format = str(self.config.get("date_format", "%Y-%m-%d"))
        self.static_params: dict[str, Any] = self.config.get("params") or {}
        self.static_body: dict[str, Any] = self.config.get("body") or {}
        self.headers: dict[str, str] = self.config.get("headers") or {}

    # -- pobieranie --------------------------------------------------------

    def fetch(self, ctx: FetchContext) -> Iterator[Tender]:
        seen = 0
        wydane: set[str] = set()
        widziane_rekordy: set[str] = set()
        for offset in range(self.max_pages or ctx.settings.max_pages):
            if ctx.wyczerpany_czas():
                log.warning(
                    "Źródło '%s': wyczerpany budżet czasu po %s stronach — "
                    "oddaję to, co udało się pobrać",
                    self.key, offset,
                )
                break
            page = self.first_page + offset
            data = self._request(ctx, page)
            rows = self._rows(data)
            # Koniec listy poznajemy po pustej stronie, a nie po tym, że
            # zwrócono mniej pozycji, niż prosiliśmy: serwer bywa ograniczony
            # własnym limitem (e-Zamówienia oddają 10 pozycji na 100 żądanych)
            # i zatrzymalibyśmy się po pierwszej stronie.
            if not rows:
                break

            # Zabezpieczenie liczymy na surowych rekordach, a nie na tych
            # zachowanych: cała strona może zostać odsiana przez `skip_kinds`
            # (w BZP pierwsza strona bywa samymi planami postępowań), a to nie
            # znaczy, że dalszych stron nie ma.
            klucze = {self._row_key(row) for row in rows}
            nowe_rekordy = klucze - widziane_rekordy
            widziane_rekordy |= klucze

            for row in rows:
                tender = self._to_tender(row)
                if tender is None or tender.id in wydane:
                    continue
                wydane.add(tender.id)
                seen += 1
                yield tender
                if seen >= ctx.limit:
                    return

            if not nowe_rekordy:
                # Źródło ignoruje numer strony i oddaje wciąż to samo —
                # dalsze pobieranie tylko marnowałoby czas przebiegu.
                log.warning(
                    "Źródło '%s': strona %s powtarza poprzednie rekordy — kończę",
                    self.key, page,
                )
                break

    def _request(self, ctx: FetchContext, page: int) -> Any:
        placeholders = {
            "page": page,
            "page_size": self.page_size,
            "date_from": ctx.date_from.strftime(self.date_format),
            "date_to": ctx.date_to.strftime(self.date_format),
            "offset": (page - self.first_page) * self.page_size,
            # Warianty pełnych znaczników czasu — część API wymaga zakresu
            # od północy do końca dnia, inaczej gubi ogłoszenia z dzisiaj.
            "date_from_iso": f"{ctx.date_from.isoformat()}T00:00:00.000Z",
            "date_to_iso": f"{ctx.date_to.isoformat()}T23:59:59.999Z",
        }
        kwargs: dict[str, Any] = {"timeout": ctx.limit_czasu_zadania()}
        if self.headers:
            kwargs["headers"] = self.headers
        if self.static_params:
            kwargs["params"] = _fill(self.static_params, placeholders)

        if self.method == "POST":
            kwargs["json"] = _fill(self.static_body, placeholders)
            return ctx.http.post_json(self.url, **kwargs)
        return ctx.http.get_json(self.url, **kwargs)

    def _rows(self, data: Any) -> list[dict[str, Any]]:
        if self.result_path:
            found = dig(data, self.result_path)
            if isinstance(found, list):
                return [row for row in found if isinstance(row, dict)]
            log.warning(
                "Źródło '%s': pod ścieżką '%s' nie ma listy — próbuję kluczy domyślnych",
                self.key, self.result_path,
            )
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            for key in FALLBACK_RESULT_KEYS:
                value = pick_ci(data, key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]
        return []

    # -- mapowanie ---------------------------------------------------------

    def _value(self, row: dict[str, Any], field: str) -> Any:
        """Czyta pole wg mapowania z YAML-a; brak mapowania = nazwa pola."""
        keys = self.field_map.get(field, field)
        if isinstance(keys, str):
            keys = [keys]
        if not isinstance(keys, (list, tuple)):
            return None
        return pick_ci(row, *[str(k) for k in keys])

    def _row_key(self, row: dict[str, Any]) -> str:
        """Identyfikator surowego rekordu — do wykrycia powtórzonej strony."""
        return first_text(self._value(row, "native_id")) or _fallback_id(row) or repr(sorted(row))

    def _kind(self, row: dict[str, Any]) -> str | None:
        """Rodzaj wpisu dla rekordu; None oznacza „pomiń to ogłoszenie”."""
        if not self.kind_field:
            return self.kind
        wartosc = first_text(pick_ci(row, self.kind_field))
        if wartosc in self.skip_kinds:
            return None
        return self.kind_map.get(wartosc, self.kind)

    def _to_tender(self, row: dict[str, Any]) -> Tender | None:
        title = collapse_whitespace(first_text(self._value(row, "title")))
        native_id = first_text(self._value(row, "native_id")) or _fallback_id(row)
        if not title or not native_id:
            return None

        rodzaj = self._kind(row)
        if rodzaj is None:
            return None

        cpv = extract_cpv_codes(self._value(row, "cpv"))
        url = first_text(self._value(row, "url"))
        if not url and self.detail_url:
            url = _fill_template(self.detail_url, row, native_id)

        return Tender(
            id=f"{self.key}:{native_id}",
            source=self.key,
            native_id=native_id,
            title=title,
            url=url,
            description=first_text(self._value(row, "description")),
            buyer=first_text(self._value(row, "buyer")),
            location=first_text(self._value(row, "location")),
            cpv=cpv,
            kind=rodzaj,
            publication_date=parse_date(self._value(row, "publication_date")),
            deadline=parse_date(self._value(row, "deadline")),
            value=to_float(self._value(row, "value")),
            currency=first_text(self._value(row, "currency")).upper()[:3],
        ).normalized()


def _fallback_id(row: dict[str, Any]) -> str:
    """Gdy YAML nie wskazał identyfikatora, sięgamy po typowe nazwy pól."""
    return first_text(
        pick_ci(row, "id", "noticeNumber", "bzpNumber", "objectId", "guid", "uuid", "number")
    )


def _fill(template: Any, values: dict[str, Any]) -> Any:
    """Podstawia {page}, {date_from}, {date_to}, {offset} w konfiguracji."""
    if isinstance(template, str):
        try:
            filled = template.format(**values)
        except (KeyError, IndexError, ValueError):
            return template
        # Zachowaj typ liczbowy, gdy cały napis to podstawiony numer strony.
        return int(filled) if template.strip("{}") in values and filled.isdigit() else filled
    if isinstance(template, dict):
        return {k: _fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, values) for v in template]
    return template


def _fill_template(template: str, row: dict[str, Any], native_id: str) -> str:
    """Buduje adres szczegółów ogłoszenia, np. '.../details/{id}'."""
    out = template.replace("{id}", native_id)
    while "{" in out and "}" in out:
        start = out.index("{")
        end = out.index("}", start)
        field = out[start + 1 : end]
        out = out[:start] + first_text(pick_ci(row, field)) + out[end + 1 :]
    return out


def build_sources(config: dict[str, Any]) -> list[GenericJsonSource]:
    """Tworzy adaptery z sekcji `sources:` pliku konfiguracyjnego."""
    sources = []
    for key, entry in (config or {}).items():
        if not isinstance(entry, dict) or entry.get("type") != "json":
            continue
        try:
            source = GenericJsonSource(key, entry)
        except SourceError as exc:
            log.error("Pomijam źródło '%s': %s", key, exc)
            continue
        if source.enabled:
            sources.append(source)
    return sources
