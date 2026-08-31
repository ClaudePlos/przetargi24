"""Diagnostyka źródeł, runda 4 — realne stronicowanie BZP i pola planów."""

from __future__ import annotations

import collections
import datetime as dt
import json

import requests

TIMEOUT = 30
HEADERS = {"User-Agent": "Przetargi24/1.0 (diagnostyka)", "Accept": "application/json"}
BOARD = "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search"
DZIS = dt.date.today()


def pobierz(**parametry):
    odp = requests.get(BOARD, params=parametry, headers=HEADERS, timeout=TIMEOUT)
    if odp.status_code >= 400:
        return odp.status_code, None
    dane = odp.json()
    return odp.status_code, dane if isinstance(dane, list) else None


def ile_na_stronie() -> None:
    print("=" * 78)
    print("BZP — jaki jest realny rozmiar strony")
    print("=" * 78)
    for rozmiar in (10, 20, 50, 100, 200):
        status, dane = pobierz(PageNumber=1, PageSize=rozmiar)
        print(f"  PageSize={rozmiar:4} -> HTTP {status}, otrzymano {len(dane) if dane is not None else 'n/d'}")


def sortowanie() -> None:
    print("\n" + "=" * 78)
    print("BZP — czy działa sortowanie malejąco po dacie")
    print("=" * 78)
    warianty = [
        {},
        {"SortingColumnName": "PublicationDate", "SortingDirection": "DESC"},
        {"SortingColumnName": "publicationDate", "SortingDirection": "Descending"},
        {"OrderBy": "PublicationDate", "OrderDirection": "DESC"},
    ]
    for dodatki in warianty:
        status, dane = pobierz(PageNumber=1, PageSize=3, **dodatki)
        daty = [str(x.get("publicationDate"))[:10] for x in (dane or [])]
        print(f"  {json.dumps(dodatki, ensure_ascii=False)[:64]:66} HTTP {status}, daty: {daty}")


def stronicowanie_z_datami() -> None:
    print("\n" + "=" * 78)
    print("BZP — ile naprawdę jest ogłoszeń z ostatnich 7 dni (stronicowanie do skutku)")
    print("=" * 78)
    rodzaje: collections.Counter = collections.Counter()
    razem, puste_pola = 0, collections.Counter()
    plan_przyklad = None

    for strona in range(1, 26):
        status, dane = pobierz(
            PageNumber=strona,
            PageSize=100,
            PublicationDateFrom=(DZIS - dt.timedelta(days=7)).isoformat(),
            PublicationDateTo=DZIS.isoformat(),
        )
        if dane is None:
            print(f"  strona {strona}: HTTP {status} — przerywam")
            break
        if not dane:
            print(f"  strona {strona}: pusta — koniec listy")
            break
        razem += len(dane)
        for pozycja in dane:
            rodzaj = str(pozycja.get("noticeType"))
            rodzaje[rodzaj] += 1
            if pozycja.get("orderObject") in (None, ""):
                puste_pola[rodzaj] += 1
            if rodzaj == "TenderPlanNotice" and plan_przyklad is None:
                plan_przyklad = pozycja
        if strona <= 3 or strona % 5 == 0:
            print(f"  strona {strona}: {len(dane)} pozycji (narastająco {razem})")

    print(f"\nŁącznie pobrano {razem} ogłoszeń.")
    print("\nRodzaje (noticeType) i ile z nich ma pusty orderObject:")
    for rodzaj, ile in rodzaje.most_common():
        print(f"  {rodzaj:32} {ile:5}   pusty tytuł: {puste_pola[rodzaj]}")

    if plan_przyklad:
        print("\nPełny rekord planu postępowań (TenderPlanNotice):")
        for klucz in sorted(plan_przyklad):
            wartosc = plan_przyklad[klucz]
            tekst = wartosc if isinstance(wartosc, str) else json.dumps(wartosc, ensure_ascii=False)
            print(f"  {klucz:32} = {tekst[:96] if tekst else tekst}")


if __name__ == "__main__":
    ile_na_stronie()
    sortowanie()
    stronicowanie_z_datami()
