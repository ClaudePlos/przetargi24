"""Testy silnika alertów — dopasowanie, treść i rozsyłka, wszystko bez sieci."""

import datetime as dt

import pytest

from przetargi.alerty import (
    Alert,
    KlientSupabase,
    RaportAlertow,
    WysylkaResend,
    dopasuj,
    pasuje,
    wyslij_alerty,
    zbuduj_wiadomosc,
)
from przetargi.models import Tender

DZIS = dt.date(2026, 9, 1)


def _tender(tid="t:1", **kwargs):
    base = dict(
        id=tid, source="ted", native_id=tid, title="Sprzątanie biur",
        categories=["sprzatanie"], location="PL213", url="https://example.invalid/1",
    )
    base.update(kwargs)
    return Tender(**base)


def _alert(**kwargs):
    base = dict(id="a1", email="firma@example.invalid", nazwa="Mój alert")
    base.update(kwargs)
    return Alert(**base)


# --- dopasowanie ----------------------------------------------------------

def test_pusty_alert_lapie_wszystko():
    assert pasuje(_alert(), _tender())


def test_filtr_kategorii():
    alert = _alert(kategorie=["sprzatanie"])
    assert pasuje(alert, _tender(categories=["sprzatanie"]))
    assert not pasuje(alert, _tender(categories=["catering"]))
    # Wystarczy jedna wspólna kategoria.
    assert pasuje(alert, _tender(categories=["catering", "sprzatanie"]))


def test_filtr_fraz_ignoruje_wielkosc_liter_i_ogonki():
    alert = _alert(frazy=["sprzatanie"])
    assert pasuje(alert, _tender(title="SPRZĄTANIE obiektów"))
    assert not pasuje(alert, _tender(title="Dostawa mebli", categories=[]))


def test_filtr_cpv_dopasowuje_po_przedrostku():
    alert = _alert(cpv=["9091"])
    assert pasuje(alert, _tender(cpv=["90911200-8"]))
    assert not pasuje(alert, _tender(cpv=["15800000-6"]))


def test_filtr_wojewodztwa_po_kodzie_lub_miescie():
    assert pasuje(_alert(wojewodztwa=["PL21"]), _tender(location="PL213"))
    assert pasuje(_alert(wojewodztwa=["Kraków"]), _tender(location="Kraków"))
    assert not pasuje(_alert(wojewodztwa=["PL21"]), _tender(location="PL911"))


def test_wartosc_minimalna():
    alert = _alert(wartosc_min=100000)
    assert pasuje(alert, _tender(value=250000.0))
    assert not pasuje(alert, _tender(value=50000.0))


def test_brak_wartosci_nie_dyskwalifikuje():
    """Wiele ogłoszeń nie podaje kwoty — ukrywanie ich gubiłoby realne szanse."""
    assert pasuje(_alert(wartosc_min=100000), _tender(value=None))


def test_warunki_lacza_sie_koniunkcja():
    alert = _alert(kategorie=["sprzatanie"], wojewodztwa=["PL21"])
    assert pasuje(alert, _tender(categories=["sprzatanie"], location="PL213"))
    # Kategoria pasuje, ale region już nie.
    assert not pasuje(alert, _tender(categories=["sprzatanie"], location="PL911"))


def test_dopasuj_sortuje_od_najnowszych():
    stare = _tender("t:1", publication_date="2026-08-20")
    nowe = _tender("t:2", publication_date="2026-08-30")
    assert [t.id for t in dopasuj(_alert(), [stare, nowe])] == ["t:2", "t:1"]


# --- treść wiadomości -----------------------------------------------------

def test_temat_i_odmiana_dla_jednego_ogloszenia():
    temat, tresc_html, tekst = zbuduj_wiadomosc(_alert(), [_tender()], "https://p.invalid")
    assert "1 nowe ogłoszenie" in temat
    assert "1 nowe ogłoszenie pasujące do alertu" in tekst
    assert "pasujące do alertu" in tresc_html


def test_odmiana_dla_wielu_ogloszen():
    lista = [_tender(f"t:{i}") for i in range(3)]
    temat, _, tekst = zbuduj_wiadomosc(_alert(), lista, "https://p.invalid")
    assert "3 nowych ogłoszeń" in temat
    assert "pasujących do alertu" in tekst


def test_dluga_lista_jest_skracana():
    lista = [_tender(f"t:{i}") for i in range(40)]
    _, tresc_html, tekst = zbuduj_wiadomosc(_alert(), lista, "https://p.invalid")
    assert tresc_html.count("<li") == 15
    assert "i 25 dalszych" in tekst


def test_termin_pokazuje_ile_zostalo():
    _, _, tekst = zbuduj_wiadomosc(
        _alert(), [_tender(deadline="2026-09-11")], "https://p.invalid", DZIS
    )
    assert "za 10 dni" in tekst


def test_tresc_jest_escapowana():
    """Tytuł pochodzi z zewnętrznego rejestru — nie może wstrzyknąć znaczników."""
    zlosliwy = _tender(title="<script>alert(1)</script> Sprzątanie", buyer="<b>X</b>")
    _, tresc_html, _ = zbuduj_wiadomosc(_alert(), [zlosliwy], "https://p.invalid")
    assert "<script>" not in tresc_html
    assert "&lt;script&gt;" in tresc_html
    assert "<b>X</b>" not in tresc_html


# --- rozsyłka -------------------------------------------------------------

class FalszywyHttp:
    def __init__(self, alerty=None, wyslane=None):
        self.alerty = alerty if alerty is not None else []
        self.wyslane_wiersze = wyslane if wyslane is not None else []
        self.wyslane_maile = []
        self.zapisy = []

    def get_json(self, url, **kwargs):
        if "/alert" in url:
            return self.alerty
        if "/wyslane" in url:
            return self.wyslane_wiersze
        return []

    def post_json(self, url, **kwargs):
        if "resend" in url:
            self.wyslane_maile.append(kwargs["json"])
        else:
            self.zapisy.extend(kwargs["json"])
        return {}


def _uslugi(http):
    return (
        KlientSupabase("https://baza.invalid", "klucz-serwisowy", http),
        WysylkaResend("klucz-poczty", "alerty@example.invalid", http),
    )


WIERSZ_ALERTU = {
    "id": "a1", "nazwa": "Sprzątanie", "kategorie": ["sprzatanie"],
    "frazy": [], "cpv": [], "wojewodztwa": [], "wartosc_min": None,
    "profile": {"email": "firma@example.invalid", "plan": "premium"},
}


def test_wysylka_trafia_do_wlasciciela_alertu():
    http = FalszywyHttp(alerty=[WIERSZ_ALERTU])
    baza, poczta = _uslugi(http)
    raport = wyslij_alerty(baza, poczta, [_tender()], "https://p.invalid", DZIS)

    assert raport.wyslanych == 1 and raport.ogloszen == 1 and raport.bledow == 0
    assert http.wyslane_maile[0]["to"] == ["firma@example.invalid"]
    assert "Sprzątanie" in http.wyslane_maile[0]["subject"]


def test_nie_wysyla_gdy_nic_nie_pasuje():
    http = FalszywyHttp(alerty=[WIERSZ_ALERTU])
    baza, poczta = _uslugi(http)
    raport = wyslij_alerty(baza, poczta, [_tender(categories=["catering"])])

    assert raport.wyslanych == 0
    assert http.wyslane_maile == []


def test_nie_wysyla_drugi_raz_tego_samego_ogloszenia():
    """Automat bywa uruchamiany kilka razy dziennie — dziennik chroni przed duplikatem."""
    http = FalszywyHttp(alerty=[WIERSZ_ALERTU], wyslane=[{"ogloszenie": "t:1"}])
    baza, poczta = _uslugi(http)
    raport = wyslij_alerty(baza, poczta, [_tender("t:1")])

    assert raport.wyslanych == 0
    assert http.wyslane_maile == []


def test_zapisuje_dziennik_po_wyslaniu():
    http = FalszywyHttp(alerty=[WIERSZ_ALERTU])
    baza, poczta = _uslugi(http)
    wyslij_alerty(baza, poczta, [_tender("t:1"), _tender("t:2")])

    assert {z["ogloszenie"] for z in http.zapisy} == {"t:1", "t:2"}


def test_brak_nowych_ogloszen_konczy_bez_zapytan():
    http = FalszywyHttp(alerty=[WIERSZ_ALERTU])
    baza, poczta = _uslugi(http)
    raport = wyslij_alerty(baza, poczta, [])

    assert raport == RaportAlertow()
    assert http.wyslane_maile == []


def test_blad_jednego_alertu_nie_blokuje_pozostalych():
    class HttpZBledem(FalszywyHttp):
        def post_json(self, url, **kwargs):
            if "resend" in url and not self.wyslane_maile:
                self.wyslane_maile.append(None)  # licznik pierwszej próby
                raise RuntimeError("usługa pocztowa nie odpowiada")
            return super().post_json(url, **kwargs)

    drugi = {**WIERSZ_ALERTU, "id": "a2",
             "profile": {"email": "druga@example.invalid", "plan": "premium"}}
    http = HttpZBledem(alerty=[WIERSZ_ALERTU, drugi])
    baza, poczta = _uslugi(http)
    raport = wyslij_alerty(baza, poczta, [_tender()])

    assert raport.bledow == 1
    assert raport.wyslanych == 1


def test_alert_bez_adresu_jest_pomijany():
    bez_maila = {**WIERSZ_ALERTU, "profile": {"email": "", "plan": "premium"}}
    http = FalszywyHttp(alerty=[bez_maila])
    baza, poczta = _uslugi(http)
    raport = wyslij_alerty(baza, poczta, [_tender()])

    assert raport.wyslanych == 0 and http.wyslane_maile == []


def test_zapytanie_o_alerty_filtruje_po_planie_premium():
    """Konto darmowe nie ma dostawać alertów — filtr jest w zapytaniu do bazy."""
    zapamietane = {}

    class HttpZapisujacy(FalszywyHttp):
        def get_json(self, url, **kwargs):
            if "/alert" in url:
                zapamietane.update(kwargs.get("params") or {})
            return super().get_json(url, **kwargs)

    http = HttpZapisujacy(alerty=[])
    baza, _ = _uslugi(http)
    baza.aktywne_alerty()

    assert zapamietane["profile.plan"] == "eq.premium"
    assert zapamietane["aktywny"] == "eq.true"


def test_alert_z_wiersza_bazy():
    alert = Alert.from_row(WIERSZ_ALERTU)
    assert alert.id == "a1"
    assert alert.email == "firma@example.invalid"
    assert alert.kategorie == ["sprzatanie"]


def test_alert_z_wiersza_gdy_profil_jest_lista():
    """PostgREST bywa zwraca zagnieżdżony select jako listę."""
    alert = Alert.from_row({**WIERSZ_ALERTU, "profile": [{"email": "a@b.invalid"}]})
    assert alert.email == "a@b.invalid"
