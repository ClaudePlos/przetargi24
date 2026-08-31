import datetime as dt

import pytest

from przetargi.models import KIND_PLAN
from przetargi.sources import build_sources
from przetargi.sources.base import (
    FetchContext,
    SourceError,
    all_texts,
    dig,
    first_text,
    pick_ci,
    to_float,
)
from przetargi.sources.generic import GenericJsonSource, _fill
from przetargi.sources.ted import TedSource, _build_query, _extract_notices


# --- odporne wyciąganie wartości -----------------------------------------

def test_first_text_z_mapy_jezykowej():
    assert first_text({"pol": ["Sprzątanie"], "eng": ["Cleaning"]}) == "Sprzątanie"


def test_first_text_wybiera_polski_gdy_dostepny():
    assert first_text({"eng": ["Cleaning"], "pol": ["Sprzątanie"]}) == "Sprzątanie"


def test_first_text_schodzi_do_pierwszej_niepustej_wartosci():
    assert first_text([{"deu": []}, "", "Wartość"]) == "Wartość"
    assert first_text(None) == ""


def test_all_texts_splaszcza_i_odsiewa_duplikaty():
    assert all_texts({"pol": ["A", "B", "A"]}) == ["A", "B"]
    assert all_texts([{"x": "1"}, {"y": ["2", "3"]}]) == ["1", "2", "3"]


@pytest.mark.parametrize(
    "raw,expected",
    [("1 234,56", 1234.56), ("1234.56 PLN", 1234.56), ({"amount": "99"}, 99.0),
     (None, None), ("brak", None), (["x", "12"], 12.0)],
)
def test_to_float(raw, expected):
    assert to_float(raw) == expected


def test_pick_ci_ignoruje_wielkosc_liter_i_separatory():
    row = {"PublicationDate": "2026-08-30", "order-object": "Sprzątanie"}
    assert pick_ci(row, "publicationdate") == "2026-08-30"
    assert pick_ci(row, "OrderObject") == "Sprzątanie"
    assert pick_ci(row, "brak", "order_object") == "Sprzątanie"
    assert pick_ci(row, "nie-ma") is None


def test_pick_ci_obsluguje_sciezke_z_kropka():
    assert pick_ci({"Buyer": {"Name": "Gmina X"}}, "buyer.name") == "Gmina X"


def test_dig():
    assert dig({"d": {"items": [1, 2]}}, "d.items") == [1, 2]
    assert dig({"a": 1}, "") == {"a": 1}
    assert dig({"a": 1}, "x.y") is None


# --- TED ------------------------------------------------------------------

def test_ted_query_zawiera_zakres_dat_i_polske():
    query = _build_query(dt.date(2026, 8, 24), dt.date(2026, 8, 31))
    assert "publication-date>=20260824" in query
    assert "publication-date<=20260831" in query
    assert "POL" in query


def test_ted_mapuje_ogloszenie():
    notice = {
        "publication-number": "123456-2026",
        "notice-title": {"pol": ["Sprzątanie obiektów"]},
        "notice-type": "cn-standard",
        "buyer-name": {"pol": ["Gmina Miasto Poznań"]},
        "classification-cpv": ["90910000", "90911200"],
        "publication-date": "2026-08-30+02:00",
        "deadline-receipt-request": "2026-09-20Z",
        "description-lot": {"pol": ["Kompleksowe sprzątanie budynków."]},
        "total-value": {"amount": 480000, "currency": "PLN"},
        "links": {"html": {"POL": "https://ted.europa.eu/pl/notice/-/detail/123456-2026"}},
    }
    tender = TedSource()._to_tender(notice)
    assert tender.id == "ted:123456-2026"
    assert tender.title == "Sprzątanie obiektów"
    assert tender.buyer == "Gmina Miasto Poznań"
    assert tender.publication_date == "2026-08-30"
    assert tender.deadline == "2026-09-20"
    assert tender.value == 480000.0 and tender.currency == "PLN"
    assert tender.url.endswith("123456-2026")


def test_ted_pin_to_plan_postepowan():
    notice = {"publication-number": "1-2026", "notice-title": "Zapowiedź", "notice-type": "pin-only"}
    assert TedSource()._to_tender(notice).kind == KIND_PLAN


def test_ted_buduje_adres_gdy_brak_linkow():
    notice = {"publication-number": "9-2026", "notice-title": "Tytuł"}
    assert TedSource()._to_tender(notice).url.startswith("https://ted.europa.eu/")


def test_ted_pomija_rekordy_bez_numeru_lub_tytulu():
    source = TedSource()
    assert source._to_tender({"notice-title": "Bez numeru"}) is None
    assert source._to_tender({"publication-number": "1-2026"}) is None
    assert source._to_tender("nie-slownik") is None


@pytest.mark.parametrize("klucz", ["notices", "results", "items", "data", "content"])
def test_ted_znajduje_liste_pod_roznymi_kluczami(klucz):
    assert len(_extract_notices({klucz: [{"a": 1}, {"b": 2}]})) == 2


def test_ted_radzi_sobie_z_odpowiedzia_bez_wynikow():
    assert _extract_notices({"totalNoticeCount": 0}) == []
    assert _extract_notices("cokolwiek") == []


# --- źródło konfigurowane YAML-em ----------------------------------------

BZP_CONFIG = {
    "label": "BZP",
    "url": "https://example.invalid/api",
    "method": "POST",
    "result_path": "items",
    "body": {"PageNumber": "{page}", "PublicationDateFrom": "{date_from}"},
    "fields": {
        "native_id": ["NoticeNumber"],
        "title": ["OrderObject"],
        "buyer": ["OrganizationName"],
        "publication_date": ["PublicationDate"],
        "deadline": ["SubmittingOffersDate"],
        "cpv": ["CpvCode"],
    },
    "detail_url": "https://example.invalid/notice/{ObjectId}",
}

ROW = {
    "NoticeNumber": "2026/BZP 00123456",
    "OrderObject": "Usługi cateringowe dla szkoły",
    "OrganizationName": "Gmina Wrocław",
    "PublicationDate": "2026-08-29T08:00:00",
    "SubmittingOffersDate": "2026-09-12T10:00:00",
    "CpvCode": "55520000-1",
    "ObjectId": "abc-123",
}


def test_generic_mapuje_wiersz_wg_konfiguracji():
    tender = GenericJsonSource("bzp", BZP_CONFIG)._to_tender(ROW)
    assert tender.id == "bzp:2026/BZP 00123456"
    assert tender.title == "Usługi cateringowe dla szkoły"
    assert tender.buyer == "Gmina Wrocław"
    assert tender.publication_date == "2026-08-29"
    assert tender.deadline == "2026-09-12"
    assert tender.cpv == ["55520000-1"]
    assert tender.url == "https://example.invalid/notice/abc-123"


def test_generic_dziala_gdy_api_zmieni_wielkosc_liter():
    """Nazwy pól porównujemy bez wielkości liter i separatorów."""
    zmieniony = {k.lower().replace("o", "o"): v for k, v in ROW.items()}
    zmieniony = {"notice_number": ROW["NoticeNumber"], "order-object": ROW["OrderObject"]}
    tender = GenericJsonSource("bzp", BZP_CONFIG)._to_tender(zmieniony)
    assert tender is not None and tender.native_id == ROW["NoticeNumber"]


def test_generic_pomija_wiersz_bez_tytulu():
    assert GenericJsonSource("bzp", BZP_CONFIG)._to_tender({"NoticeNumber": "1"}) is None


def test_generic_szuka_listy_pod_kluczem_domyslnym():
    source = GenericJsonSource("bzp", BZP_CONFIG)
    assert len(source._rows({"items": [ROW]})) == 1
    # Gdy `result_path` nie pasuje, sięgamy po typowe nazwy kluczy.
    assert len(source._rows({"list": [ROW]})) == 1
    assert source._rows({"nic": 1}) == []


def test_generic_wymaga_adresu():
    with pytest.raises(SourceError, match="url"):
        GenericJsonSource("zle", {"label": "Bez adresu"})


def test_podstawienia_w_ciele_zapytania():
    wypelnione = _fill(
        {"PageNumber": "{page}", "Od": "{date_from_iso}"},
        {"page": 2, "date_from_iso": "2026-08-24T00:00:00.000Z"},
    )
    assert wypelnione == {"PageNumber": 2, "Od": "2026-08-24T00:00:00.000Z"}


# --- rejestr --------------------------------------------------------------

def test_build_sources_z_prawdziwej_konfiguracji(config):
    klucze = [s.key for s in build_sources(config.sources)]
    assert "ted" in klucze and "bzp" in klucze


def test_build_sources_pomija_wylaczone():
    konfiguracja = {"sources": {"ted": {"type": "builtin", "enabled": False},
                                "x": {"type": "json", "url": "https://a.invalid"}}}
    assert [s.key for s in build_sources(konfiguracja)] == ["x"]


def test_build_sources_bez_zrodel_to_blad():
    with pytest.raises(SourceError):
        build_sources({"sources": {}})


@pytest.mark.parametrize(
    "rodzaj", ["can-standard", "can-modif", "can-desg", "cm-standard", "veat", "compl"]
)
def test_ted_pomija_ogloszenia_o_wyniku_i_zmianie_umowy(rodzaj):
    """Ogłoszenie o wyniku to nie okazja — nie ma po co trafiać do portalu."""
    notice = {"publication-number": "1-2026", "notice-title": "Tytuł", "notice-type": rodzaj}
    assert TedSource()._to_tender(notice) is None


@pytest.mark.parametrize("rodzaj", ["cn-standard", "cn-social", "pin-rtl", "pin-tran", ""])
def test_ted_zachowuje_ogloszenia_i_zapowiedzi(rodzaj):
    notice = {"publication-number": "1-2026", "notice-title": "Tytuł", "notice-type": rodzaj}
    assert TedSource()._to_tender(notice) is not None


def test_ted_zachowuje_nieznany_rodzaj():
    """Nowy typ w TED lepiej pokazać niż po cichu zgubić."""
    notice = {"publication-number": "1-2026", "notice-title": "Tytuł", "notice-type": "xyz-nowy"}
    assert TedSource()._to_tender(notice) is not None


# --- rodzaj wpisu i stronicowanie w źródle konfigurowanym -----------------

KONFIG_Z_RODZAJEM = {
    **BZP_CONFIG,
    "kind_field": "noticeType",
    "kind_map": {"TenderPlanNotice": "plan"},
    "skip_kinds": ["TenderResultNotice", "ContractPerformingNotice"],
}


def test_rodzaj_wpisu_z_pola_rekordu():
    source = GenericJsonSource("bzp", KONFIG_Z_RODZAJEM)
    assert source._to_tender({**ROW, "noticeType": "ContractNotice"}).kind == "ogloszenie"
    assert source._to_tender({**ROW, "noticeType": "TenderPlanNotice"}).kind == "plan"


@pytest.mark.parametrize("rodzaj", ["TenderResultNotice", "ContractPerformingNotice"])
def test_pomijane_rodzaje_wypadaja(rodzaj):
    source = GenericJsonSource("bzp", KONFIG_Z_RODZAJEM)
    assert source._to_tender({**ROW, "noticeType": rodzaj}) is None


def test_nieznany_rodzaj_zostaje_zachowany():
    source = GenericJsonSource("bzp", KONFIG_Z_RODZAJEM)
    assert source._to_tender({**ROW, "noticeType": "CosNowego"}) is not None
    assert source._to_tender({**ROW, "noticeType": None}) is not None


def test_kody_cpv_z_napisu_z_etykietami():
    """BZP oddaje wszystkie kody w jednym polu tekstowym z opisami."""
    row = {**ROW, "CpvCode": "90910000-9 (Usługi sprzątania),90911300-9 (Usługi czyszczenia okien)"}
    tender = GenericJsonSource("bzp", BZP_CONFIG)._to_tender(row)
    assert tender.cpv == ["90910000-9", "90911300-9"]


class _KontekstStron:
    """Podstawia odpowiedzi kolejnych stron zamiast prawdziwego HTTP."""

    def __init__(self, strony):
        self.strony = strony
        self.zapytania = 0

    def get_json(self, url, **kwargs):
        self.zapytania += 1
        indeks = self.zapytania - 1
        return self.strony[indeks] if indeks < len(self.strony) else []

    post_json = get_json


def _kontekst(strony, max_pages=10, limit=100):
    from types import SimpleNamespace

    return FetchContext(
        settings=SimpleNamespace(max_pages=max_pages),
        date_from=dt.date(2026, 8, 24),
        date_to=dt.date(2026, 8, 31),
        http=_KontekstStron(strony),
        limit=limit,
    )


def _wiersz(numer):
    return {**ROW, "NoticeNumber": f"2026/BZP {numer:08d}"}


def test_stronicowanie_nie_konczy_sie_na_krotszej_stronie():
    """Serwer oddaje mniej pozycji, niż prosimy — to nie znaczy koniec listy.

    e-Zamówienia zwracają 10 rekordów niezależnie od PageSize, więc warunek
    'mniej niż żądano' zatrzymywałby pobieranie po pierwszej stronie.
    """
    strony = [[_wiersz(1), _wiersz(2)], [_wiersz(3), _wiersz(4)], []]
    config = {**BZP_CONFIG, "page_size": 50}
    ctx = _kontekst(strony)
    wyniki = list(GenericJsonSource("bzp", config).fetch(ctx))
    assert len(wyniki) == 4


def test_stronicowanie_konczy_sie_na_pustej_stronie():
    ctx = _kontekst([[_wiersz(1)], []])
    wyniki = list(GenericJsonSource("bzp", BZP_CONFIG).fetch(ctx))
    assert len(wyniki) == 1
    assert ctx.http.zapytania == 2


def test_stronicowanie_przerywa_gdy_zrodlo_oddaje_wciaz_to_samo():
    """Zabezpieczenie przed źródłem ignorującym numer strony."""
    ctx = _kontekst([[_wiersz(1)]] * 10, max_pages=10)
    wyniki = list(GenericJsonSource("bzp", BZP_CONFIG).fetch(ctx))
    assert len(wyniki) == 1
    assert ctx.http.zapytania == 2  # druga strona bez nowych pozycji kończy pobieranie


def test_limit_stron_z_konfiguracji_zrodla():
    ctx = _kontekst([[_wiersz(n)] for n in range(1, 12)], max_pages=10)
    source = GenericJsonSource("bzp", {**BZP_CONFIG, "max_pages": 3})
    assert len(list(source.fetch(ctx))) == 3


def test_limit_ogloszen_konczy_pobieranie():
    ctx = _kontekst([[_wiersz(n) for n in range(1, 6)], [_wiersz(n) for n in range(6, 11)]], limit=7)
    assert len(list(GenericJsonSource("bzp", BZP_CONFIG).fetch(ctx))) == 7
