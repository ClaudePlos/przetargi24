"""Diagnostyka źródeł — uruchamiana w GitHub Actions, gdzie jest dostęp do sieci.

Sprawdza, które adresy i metody akceptują serwisy zamówień, oraz jakie pola
naprawdę wracają z TED. Wynik służy do poprawienia config/sources.yml.
"""

from __future__ import annotations

import collections
import json
import sys

import requests

TIMEOUT = 30
HEADERS = {"User-Agent": "Przetargi24/1.0 (diagnostyka)", "Accept": "application/json"}

KANDYDACI_BZP = [
    ("GET", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search"),
    ("POST", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search"),
    ("GET", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/SearchList"),
    ("POST", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/SearchList"),
    ("GET", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Notices"),
    ("GET", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/GetNotices"),
    ("GET", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/TenderPlans"),
    ("GET", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/SearchTenderPlans"),
    ("GET", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Plans"),
    ("POST", "https://ezamowienia.gov.pl/mo-board/api/v1/Board/SearchPlans"),
]

PARAMETRY = {"PageNumber": 1, "PageSize": 5, "SortingColumnName": "PublicationDate",
             "SortingDirection": "DESC"}


def opisz_odpowiedz(odpowiedz: requests.Response) -> str:
    """Zwięzły opis: status, dozwolone metody, kształt danych."""
    czesci = [f"HTTP {odpowiedz.status_code}"]
    if "Allow" in odpowiedz.headers:
        czesci.append(f"Allow: {odpowiedz.headers['Allow']}")
    typ = odpowiedz.headers.get("Content-Type", "")
    czesci.append(typ.split(";")[0] or "brak typu")

    if odpowiedz.status_code < 400 and "json" in typ:
        try:
            dane = odpowiedz.json()
        except ValueError:
            czesci.append("(treść nie jest JSON-em)")
            return " | ".join(czesci)
        if isinstance(dane, dict):
            czesci.append(f"klucze: {sorted(dane)[:8]}")
            for klucz, wartosc in dane.items():
                if isinstance(wartosc, list) and wartosc and isinstance(wartosc[0], dict):
                    czesci.append(f"lista '{klucz}' ({len(wartosc)}), pola: {sorted(wartosc[0])[:14]}")
                    break
        elif isinstance(dane, list):
            czesci.append(f"lista ({len(dane)})")
            if dane and isinstance(dane[0], dict):
                czesci.append(f"pola: {sorted(dane[0])[:14]}")
    elif odpowiedz.status_code >= 400:
        czesci.append(repr(odpowiedz.text[:160]))
    return " | ".join(czesci)


def probuj_bzp() -> None:
    print("=" * 78)
    print("BZP / e-Zamówienia — które adresy i metody odpowiadają")
    print("=" * 78)
    for metoda, url in KANDYDACI_BZP:
        try:
            if metoda == "POST":
                odpowiedz = requests.post(url, json=PARAMETRY, headers=HEADERS, timeout=TIMEOUT)
            else:
                odpowiedz = requests.get(url, params=PARAMETRY, headers=HEADERS, timeout=TIMEOUT)
            print(f"\n{metoda:5} {url}\n      {opisz_odpowiedz(odpowiedz)}")
        except requests.RequestException as exc:
            print(f"\n{metoda:5} {url}\n      BŁĄD SIECI: {type(exc).__name__}: {exc}")


def zbadaj_ted() -> None:
    """Jakie rodzaje ogłoszeń i jak wypełnione pola wracają z TED."""
    print("\n" + "=" * 78)
    print("TED — rozkład rodzajów ogłoszeń i wypełnienie pól (3 strony po 100)")
    print("=" * 78)

    pola = [
        "publication-number", "publication-date", "notice-title", "notice-type",
        "buyer-name", "classification-cpv", "deadline-receipt-request",
        "description-lot", "place-of-performance", "total-value", "links",
    ]
    rodzaje: collections.Counter = collections.Counter()
    wypelnienie: collections.Counter = collections.Counter()
    razem = 0
    przyklad = None

    for strona in (1, 2, 3):
        payload = {
            "query": "publication-date>=today(-7) AND publication-date<=today() "
                     "AND (place-of-performance IN (POL) OR buyer-country IN (POL))",
            "fields": pola,
            "page": strona,
            "limit": 100,
            "scope": "ALL",
            "paginationMode": "PAGE_NUMBER",
            "onlyLatestVersions": True,
        }
        try:
            odpowiedz = requests.post(
                "https://api.ted.europa.eu/v3/notices/search",
                json=payload, headers=HEADERS, timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            print(f"BŁĄD SIECI na stronie {strona}: {exc}")
            return
        if odpowiedz.status_code >= 400:
            print(f"Strona {strona}: HTTP {odpowiedz.status_code} — {odpowiedz.text[:300]}")
            return

        dane = odpowiedz.json()
        ogloszenia = dane.get("notices") or []
        if strona == 1:
            print(f"Klucze odpowiedzi: {sorted(dane)}")
            print(f"Łącznie w zakresie: {dane.get('totalNoticeCount')}")
        for ogloszenie in ogloszenia:
            razem += 1
            rodzaje[str(ogloszenie.get("notice-type"))] += 1
            for pole in pola:
                if ogloszenie.get(pole) not in (None, "", [], {}):
                    wypelnienie[pole] += 1
            if przyklad is None:
                przyklad = ogloszenie
        if not ogloszenia:
            break

    print(f"\nZbadano {razem} ogłoszeń.")
    print("\nRodzaje ogłoszeń (notice-type):")
    for rodzaj, ile in rodzaje.most_common():
        print(f"  {rodzaj:28} {ile:5}")
    print("\nWypełnienie pól:")
    for pole in pola:
        udzial = 100 * wypelnienie[pole] / razem if razem else 0
        print(f"  {pole:28} {wypelnienie[pole]:5}  ({udzial:.0f}%)")
    if przyklad:
        print("\nPrzykładowy rekord:")
        print(json.dumps(przyklad, ensure_ascii=False, indent=1)[:1800])


if __name__ == "__main__":
    probuj_bzp()
    zbadaj_ted()
    sys.exit(0)
