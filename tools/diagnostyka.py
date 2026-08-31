"""Diagnostyka źródeł, runda 3 — rodzaje ogłoszeń BZP i adresy szczegółów."""

from __future__ import annotations

import collections
import datetime as dt

import requests

TIMEOUT = 30
HEADERS = {"User-Agent": "Przetargi24/1.0 (diagnostyka)", "Accept": "application/json"}
BOARD = "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search"


def rodzaje_ogloszen() -> None:
    print("=" * 78)
    print("BZP — rodzaje ogłoszeń z ostatnich 7 dni")
    print("=" * 78)
    dzis = dt.date.today()
    rodzaje: collections.Counter = collections.Counter()
    typy_zamowien: collections.Counter = collections.Counter()
    razem = 0
    przyklady: dict[str, str] = {}

    for strona in range(1, 9):
        odp = requests.get(
            BOARD,
            params={
                "PageNumber": strona,
                "PageSize": 100,
                "PublicationDateFrom": (dzis - dt.timedelta(days=7)).isoformat(),
                "PublicationDateTo": dzis.isoformat(),
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if odp.status_code >= 400:
            print(f"Strona {strona}: HTTP {odp.status_code}")
            break
        pozycje = odp.json()
        if not isinstance(pozycje, list) or not pozycje:
            print(f"Strona {strona}: brak dalszych pozycji (koniec).")
            break
        for pozycja in pozycje:
            razem += 1
            rodzaj = str(pozycja.get("noticeType"))
            rodzaje[rodzaj] += 1
            typy_zamowien[str(pozycja.get("orderType"))] += 1
            if rodzaj not in przyklady:
                przyklady[rodzaj] = str(pozycja.get("orderObject"))[:88]
        if len(pozycje) < 100:
            print(f"Strona {strona}: {len(pozycje)} pozycji — ostatnia strona.")
            break

    print(f"\nZbadano {razem} ogłoszeń.\n")
    print("Rodzaje (noticeType):")
    for rodzaj, ile in rodzaje.most_common():
        print(f"  {rodzaj:32} {ile:5}   np. {przyklady.get(rodzaj, '')}")
    print("\nTypy zamówienia (orderType):")
    for typ, ile in typy_zamowien.most_common():
        print(f"  {typ:32} {ile:5}")


def adresy_szczegolow() -> None:
    print("\n" + "=" * 78)
    print("BZP — który adres strony ogłoszenia działa")
    print("=" * 78)
    odp = requests.get(BOARD, params={"PageNumber": 1, "PageSize": 1},
                       headers=HEADERS, timeout=TIMEOUT)
    pozycja = odp.json()[0]
    object_id = pozycja.get("objectId")
    tender_id = pozycja.get("tenderId")
    mo_id = pozycja.get("moIdentifier")
    print(f"objectId={object_id}\ntenderId={tender_id}\nmoIdentifier={mo_id}\n")

    kandydaci = [
        f"https://ezamowienia.gov.pl/mp-client/search/list/{tender_id}",
        f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/{object_id}",
        f"https://ezamowienia.gov.pl/mo-client-board/bzp/tender-details/{tender_id}",
        f"https://ezamowienia.gov.pl/mp-client/tenders/{tender_id}",
    ]
    for url in kandydaci:
        try:
            odp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]},
                               timeout=TIMEOUT, allow_redirects=True)
            print(f"  HTTP {odp.status_code}  {url}")
        except requests.RequestException as exc:
            print(f"  BŁĄD {type(exc).__name__}  {url}")


def format_cpv() -> None:
    print("\n" + "=" * 78)
    print("BZP — format pola cpvCode w kilku rekordach")
    print("=" * 78)
    odp = requests.get(BOARD, params={"PageNumber": 1, "PageSize": 8},
                       headers=HEADERS, timeout=TIMEOUT)
    for pozycja in odp.json():
        print(f"  {str(pozycja.get('cpvCode'))[:150]}")


if __name__ == "__main__":
    rodzaje_ogloszen()
    adresy_szczegolow()
    format_cpv()
