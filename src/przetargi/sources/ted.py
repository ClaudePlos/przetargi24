"""Źródło: TED — Tenders Electronic Daily (Dziennik Urzędowy UE, seria S).

Obejmuje polskie postępowania powyżej progów unijnych oraz wstępne ogłoszenia
informacyjne (PIN), czyli zamówienia, które dopiero zostaną ogłoszone.

Dokumentacja API: https://ted.europa.eu/en/simap/developers-corner
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Iterator

from ..models import KIND_NOTICE, KIND_PLAN, Tender, parse_date
from .base import FetchContext, Source, SourceError, all_texts, first_text, pick, to_float

log = logging.getLogger(__name__)

API_URL = "https://api.ted.europa.eu/v3/notices/search"
NOTICE_URL = "https://ted.europa.eu/en/notice/-/detail/{number}"

# Pola w słowniku eForms, których używa wyszukiwarka TED v3.
FIELDS = [
    "publication-number",
    "publication-date",
    "notice-title",
    "notice-type",
    "buyer-name",
    "buyer-country",
    "classification-cpv",
    "deadline-receipt-request",
    "description-lot",
    "place-of-performance",
    "total-value",
    "links",
]

# Klucze, pod którymi API potrafi zwrócić listę ogłoszeń.
RESULT_KEYS = ("notices", "results", "items", "data", "content")

# Rodzaje ogłoszeń, które nie są okazją do złożenia oferty i nie mają wejść
# do portalu. W tygodniowej próbce polskich ogłoszeń stanowiły ok. 45%:
#   can-*  ogłoszenie o wyniku postępowania (w tym can-modif, can-desg)
#   cm-*   zmiana zawartej umowy
#   veat   zamiar udzielenia zamówienia bez uprzedniej publikacji
#   compl  zakończenie realizacji umowy
# Nieznanych rodzajów celowo nie odsiewamy — gdy TED doda nowy typ,
# lepiej pokazać go w portalu niż po cichu zgubić.
POMIJANE_RODZAJE_PREFIKSY = ("can", "cm")
POMIJANE_RODZAJE = {"veat", "compl"}


class TedSource(Source):
    key = "ted"
    label = "TED — Dziennik Urzędowy UE"
    homepage = "https://ted.europa.eu"

    def fetch(self, ctx: FetchContext) -> Iterator[Tender]:
        seen = 0
        for page in range(1, ctx.settings.max_pages + 1):
            payload = self._payload(ctx, page)
            data = self._search(ctx, payload)
            notices = _extract_notices(data)
            if not notices:
                break

            for notice in notices:
                tender = self._to_tender(notice)
                if tender is not None:
                    seen += 1
                    yield tender
                    if seen >= ctx.limit:
                        return

            # Ostatnia strona: API zwróciło mniej rekordów, niż prosiliśmy.
            if len(notices) < payload["limit"]:
                break

    # -- zapytanie ---------------------------------------------------------

    def _payload(self, ctx: FetchContext, page: int) -> dict[str, Any]:
        return {
            "query": _build_query(ctx.date_from, ctx.date_to),
            "fields": list(FIELDS),
            "page": page,
            "limit": 100,
            "scope": "ALL",
            "paginationMode": "PAGE_NUMBER",
            "onlyLatestVersions": True,
        }

    def _search(self, ctx: FetchContext, payload: dict[str, Any]) -> Any:
        """Odpytuje API, upraszczając zapytanie, gdy zostanie odrzucone.

        Gdyby TED zmienił nazwę pola albo tryb stronicowania, uproszczone
        warianty nadal zwrócą dane (w domyślnym zestawie pól) zamiast
        wywalić cały przebieg.
        """
        variants = [payload]

        without_fields = {k: v for k, v in payload.items() if k != "fields"}
        variants.append(without_fields)

        minimal = {
            "query": payload["query"],
            "page": payload["page"],
            "limit": payload["limit"],
        }
        variants.append(minimal)

        last_error: Exception | None = None
        for index, variant in enumerate(variants):
            try:
                return ctx.http.post_json(API_URL, json=variant)
            except SourceError as exc:
                last_error = exc
                if index + 1 < len(variants):
                    log.warning("TED odrzucił zapytanie (%s) — próbuję prostszy wariant", exc)
        raise SourceError(f"TED: żaden wariant zapytania nie zadziałał ({last_error})")

    # -- mapowanie ---------------------------------------------------------

    def _to_tender(self, notice: dict[str, Any]) -> Tender | None:
        if not isinstance(notice, dict):
            return None

        number = first_text(pick(notice, "publication-number", "publicationNumber", "ND", "id"))
        title = first_text(
            pick(notice, "notice-title", "title-proc", "noticeTitle", "TI", "title")
        )
        if not number or not title:
            return None

        notice_type = first_text(pick(notice, "notice-type", "noticeType", "TD")).lower()
        if _to_pominiete(notice_type):
            return None
        # Wstępne ogłoszenie informacyjne (PIN) zapowiada przyszły przetarg.
        kind = KIND_PLAN if notice_type.startswith("pin") else KIND_NOTICE

        value_raw = pick(notice, "total-value", "totalValue", "estimated-value-lot")

        return Tender(
            id=f"{self.key}:{number}",
            source=self.key,
            native_id=number,
            title=title,
            url=_notice_url(notice, number),
            description=first_text(
                pick(notice, "description-lot", "description-proc", "descriptionLot")
            ),
            buyer=first_text(
                pick(notice, "buyer-name", "organisation-name-buyer", "buyerName", "AA")
            ),
            location=first_text(
                pick(notice, "place-of-performance", "organisation-city-buyer", "placeOfPerformance")
            ),
            cpv=_cpv_codes(notice),
            kind=kind,
            publication_date=parse_date(
                pick(notice, "publication-date", "publicationDate", "PD", "dispatch-date")
            ),
            deadline=parse_date(
                pick(
                    notice,
                    "deadline-receipt-request",
                    "deadline-receipt-tender",
                    "deadlineReceiptRequest",
                    "DT",
                )
            ),
            value=to_float(value_raw),
            currency=_currency(notice, value_raw),
        ).normalized()


def _to_pominiete(notice_type: str) -> bool:
    """Czy to ogłoszenie o wyniku albo zmianie umowy, a nie okazja do oferty."""
    if not notice_type:
        return False
    return notice_type in POMIJANE_RODZAJE or notice_type.startswith(POMIJANE_RODZAJE_PREFIKSY)


def _build_query(date_from: dt.date, date_to: dt.date) -> str:
    """Zapytanie w składni TED expert search; daty w formacie RRRRMMDD."""
    start = date_from.strftime("%Y%m%d")
    end = date_to.strftime("%Y%m%d")
    return (
        f"publication-date>={start} AND publication-date<={end} "
        "AND (place-of-performance IN (POL) OR buyer-country IN (POL))"
    )


def _extract_notices(data: Any) -> list[dict[str, Any]]:
    """Wyłuskuje listę ogłoszeń niezależnie od nazwy klucza w odpowiedzi."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in RESULT_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _cpv_codes(notice: dict[str, Any]) -> list[str]:
    raw = pick(
        notice,
        "classification-cpv",
        "main-classification-cpv",
        "additional-classification-cpv",
        "cpv",
        "PC",
    )
    codes = [code for code in all_texts(raw) if any(ch.isdigit() for ch in code)]
    return codes[:12]


def _notice_url(notice: dict[str, Any], number: str) -> str:
    links = notice.get("links")
    if isinstance(links, dict):
        # links = {"html": {"POL": "..."}, "pdf": {...}} — preferujemy HTML po polsku.
        for fmt in ("html", "htmlDirect", "pdf", "xml"):
            url = first_text(links.get(fmt))
            if url.startswith("http"):
                return url
    direct = first_text(pick(notice, "url", "noticeUrl"))
    if direct.startswith("http"):
        return direct
    return NOTICE_URL.format(number=number.replace("/", "-"))


def _currency(notice: dict[str, Any], value_raw: Any) -> str:
    currency = first_text(
        pick(notice, "total-value-cur", "totalValueCurrency", "currency")
    )
    if not currency and isinstance(value_raw, dict):
        currency = first_text(pick(value_raw, "currency", "cur"))
    return currency.upper()[:3]
