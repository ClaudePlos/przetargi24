"""Diagnostyka źródeł, runda 2 — pełny kształt rekordu BZP i szukanie planów."""

from __future__ import annotations

import json

import requests

TIMEOUT = 30
HEADERS = {"User-Agent": "Przetargi24/1.0 (diagnostyka)", "Accept": "application/json"}
BOARD = "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search"


def skrot(wartosc, limit: int = 90) -> str:
    tekst = json.dumps(wartosc, ensure_ascii=False) if not isinstance(wartosc, str) else wartosc
    return tekst if len(tekst) <= limit else tekst[:limit] + "…"


def pelny_rekord_bzp() -> None:
    print("=" * 78)
    print("BZP — pełny kształt rekordu z GET /Board/Search")
    print("=" * 78)
    odpowiedz = requests.get(
        BOARD, params={"PageNumber": 1, "PageSize": 3}, headers=HEADERS, timeout=TIMEOUT
    )
    print(f"HTTP {odpowiedz.status_code}, nagłówki stronicowania: "
          f"{ {k: v for k, v in odpowiedz.headers.items() if 'age' in k.lower() or 'count' in k.lower()} }")
    dane = odpowiedz.json()
    print(f"Typ odpowiedzi: {type(dane).__name__}, elementów: {len(dane)}")
    if not dane:
        return
    rekord = dane[0]
    print(f"\nWSZYSTKIE POLA ({len(rekord)}):")
    for klucz in sorted(rekord):
        print(f"  {klucz:34} = {skrot(rekord[klucz])}")


def czy_dziala_stronicowanie_i_daty() -> None:
    print("\n" + "=" * 78)
    print("BZP — czy działa stronicowanie i filtr dat")
    print("=" * 78)
    proby = [
        {"PageNumber": 1, "PageSize": 2},
        {"PageNumber": 2, "PageSize": 2},
        {"PageNumber": 1, "PageSize": 2, "PublicationDateFrom": "2026-08-24",
         "PublicationDateTo": "2026-08-31"},
        {"PageNumber": 1, "PageSize": 2, "PublicationDateFrom": "2026-08-24T00:00:00.000Z",
         "PublicationDateTo": "2026-08-31T23:59:59.999Z"},
        {"PageNumber": 1, "PageSize": 2, "NoticeType": "TenderPlan"},
        {"PageNumber": 1, "PageSize": 2, "OrderObject": "sprzątanie"},
    ]
    for parametry in proby:
        try:
            odp = requests.get(BOARD, params=parametry, headers=HEADERS, timeout=TIMEOUT)
            dane = odp.json() if odp.status_code < 400 else None
            ile = len(dane) if isinstance(dane, list) else "n/d"
            pierwszy = ""
            if isinstance(dane, list) and dane:
                pierwszy = f" | 1. numer: {dane[0].get('noticeNumber')} " \
                           f"| data: {dane[0].get('publicationDate')} " \
                           f"| typ: {dane[0].get('noticeType')}"
            print(f"  {json.dumps(parametry, ensure_ascii=False)[:96]:98} HTTP {odp.status_code}, "
                  f"pozycji: {ile}{pierwszy}")
        except requests.RequestException as exc:
            print(f"  {parametry} -> BŁĄD {exc}")


def szukaj_planow() -> None:
    print("\n" + "=" * 78)
    print("Plany postępowań — szukanie właściwego adresu")
    print("=" * 78)
    kandydaci = [
        "https://ezamowienia.gov.pl/mo-board/api/v1/Board/SearchTenderPlan",
        "https://ezamowienia.gov.pl/mo-board/api/v1/TenderPlan/Search",
        "https://ezamowienia.gov.pl/mo-board/api/v1/TenderPlans/Search",
        "https://ezamowienia.gov.pl/mo-board/api/v1/Plan/Search",
        "https://ezamowienia.gov.pl/mo-board/api/v1/Board/TenderPlanSearch",
        "https://ezamowienia.gov.pl/mo-board/api/v1/Board/SearchPlan",
        "https://ezamowienia.gov.pl/mo-board/api/v1/BoardTenderPlan/Search",
    ]
    for url in kandydaci:
        try:
            odp = requests.get(url, params={"PageNumber": 1, "PageSize": 2},
                               headers=HEADERS, timeout=TIMEOUT)
            opis = f"HTTP {odp.status_code}"
            if odp.status_code < 400:
                dane = odp.json()
                opis += f" | {type(dane).__name__}"
                if isinstance(dane, list) and dane:
                    opis += f" ({len(dane)}) | pola: {sorted(dane[0])[:18]}"
            elif "Allow" in odp.headers:
                opis += f" | Allow: {odp.headers['Allow']}"
            print(f"  {url.split('/api/v1/')[1]:36} {opis}")
        except requests.RequestException as exc:
            print(f"  {url} -> BŁĄD {exc}")


def sprawdz_adresy_ted() -> None:
    print("\n" + "=" * 78)
    print("TED — który adres strony ogłoszenia działa")
    print("=" * 78)
    numer = "581186-2026"
    for url in (
        f"https://ted.europa.eu/pl/notice/{numer}",
        f"https://ted.europa.eu/en/notice/-/detail/{numer}",
        f"https://ted.europa.eu/pl/notice/-/detail/{numer}",
    ):
        try:
            odp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]},
                               timeout=TIMEOUT, allow_redirects=True)
            print(f"  {url}\n      HTTP {odp.status_code} | końcowy adres: {odp.url}")
        except requests.RequestException as exc:
            print(f"  {url} -> BŁĄD {exc}")


if __name__ == "__main__":
    pelny_rekord_bzp()
    czy_dziala_stronicowanie_i_daty()
    szukaj_planow()
    sprawdz_adresy_ted()
