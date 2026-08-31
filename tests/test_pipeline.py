import datetime as dt

import pytest
import requests

from przetargi.models import Tender
from przetargi.pipeline import fetch_source, run_update
from przetargi.sources.base import FetchContext, HttpClient, Source, SourceError
from przetargi.store import TenderStore

REF = dt.date(2026, 8, 31)


class ZrodloDzialajace(Source):
    key = "ok"
    label = "Źródło działające"
    homepage = "https://example.invalid"

    def fetch(self, ctx):
        yield Tender(
            id="ok:1", source="ok", native_id="1",
            title="Kompleksowe sprzątanie biur", buyer="Gmina A",
            publication_date=REF.isoformat(), deadline="2026-09-30",
        )
        yield Tender(
            id="ok:2", source="ok", native_id="2",
            title="Budowa mostu", buyer="Gmina B", publication_date=REF.isoformat(),
        )


class ZrodloPadajaceWTrakcie(Source):
    key = "czesciowe"
    label = "Źródło padające w trakcie"

    def fetch(self, ctx):
        yield Tender(
            id="czesciowe:1", source="czesciowe", native_id="1",
            title="Dostawa posiłków do szkoły", buyer="Gmina C",
            publication_date=REF.isoformat(),
        )
        raise SourceError("API przestało odpowiadać na drugiej stronie")


def _ctx():
    return FetchContext(
        settings=None, date_from=REF, date_to=REF, http=HttpClient(timeout=1, retries=1)
    )


def test_fetch_source_raportuje_sukces():
    tenders, wynik = fetch_source(ZrodloDzialajace(), _ctx())
    assert len(tenders) == 2
    assert wynik.ok and wynik.fetched == 2 and wynik.error == ""


def test_fetch_source_zwraca_czesciowe_dane_mimo_bledu():
    """Częściowy wynik jest lepszy niż pusty dzień w portalu."""
    tenders, wynik = fetch_source(ZrodloPadajaceWTrakcie(), _ctx())
    assert len(tenders) == 1
    assert not wynik.ok
    assert "przestało odpowiadać" in wynik.error


def test_run_update_klasyfikuje_i_odrzuca_niepasujace(config, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "przetargi.pipeline.build_sources",
        lambda _: [ZrodloDzialajace(), ZrodloPadajaceWTrakcie()],
    )
    store = TenderStore(tmp_path / "t.json")
    raport, zrodla = run_update(config, store, REF)

    # "Budowa mostu" nie należy do żadnej kategorii, więc nie trafia do bazy.
    assert set(store.tenders) == {"ok:1", "czesciowe:1"}
    assert raport.added == 2
    assert raport.per_category["sprzatanie"] == 1
    assert raport.per_category["catering"] == 1

    stany = {z["key"]: z["ok"] for z in zrodla}
    assert stany == {"ok": True, "czesciowe": False}


def test_run_update_przezywa_padniete_zrodlo(config, tmp_path, monkeypatch):
    class Padajace(Source):
        key, label = "zle", "Źródło niedostępne"

        def fetch(self, ctx):
            raise SourceError("połączenie odrzucone")
            yield  # pragma: no cover

    monkeypatch.setattr(
        "przetargi.pipeline.build_sources", lambda _: [Padajace(), ZrodloDzialajace()]
    )
    store = TenderStore(tmp_path / "t.json")
    raport, zrodla = run_update(config, store, REF)

    assert raport.added == 1  # dane z działającego źródła mimo awarii drugiego
    assert [z["ok"] for z in zrodla] == [False, True]


# --- klient HTTP ----------------------------------------------------------

class FalszywaOdpowiedz:
    def __init__(self, status=200, payload=None, text="{}"):
        self.status_code = status
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("to nie jest JSON")
        return self._payload


def test_klient_ponawia_po_bledzie_przejsciowym(monkeypatch):
    klient = HttpClient(timeout=1, retries=3)
    monkeypatch.setattr("przetargi.sources.base.time.sleep", lambda _: None)
    odpowiedzi = [FalszywaOdpowiedz(503), FalszywaOdpowiedz(200, {"ok": True})]
    monkeypatch.setattr(klient.session, "request", lambda *a, **k: odpowiedzi.pop(0))

    assert klient.get_json("https://example.invalid") == {"ok": True}
    assert odpowiedzi == []


def test_klient_poddaje_sie_po_wyczerpaniu_prob(monkeypatch):
    klient = HttpClient(timeout=1, retries=2)
    monkeypatch.setattr("przetargi.sources.base.time.sleep", lambda _: None)
    monkeypatch.setattr(klient.session, "request", lambda *a, **k: FalszywaOdpowiedz(503))

    with pytest.raises(SourceError, match="Nie udało się pobrać"):
        klient.get_json("https://example.invalid")


def test_klient_zglasza_czytelny_blad_gdy_odpowiedz_nie_jest_jsonem(monkeypatch):
    klient = HttpClient(timeout=1, retries=1)
    monkeypatch.setattr(
        klient.session, "request", lambda *a, **k: FalszywaOdpowiedz(200, None, "<html>błąd</html>")
    )
    with pytest.raises(SourceError, match="nie jest JSON"):
        klient.get_json("https://example.invalid")


def test_klient_nie_ponawia_bledu_4xx(monkeypatch):
    """404 nie minie samo — ponawianie tylko marnowałoby czas przebiegu."""
    klient = HttpClient(timeout=1, retries=3)
    proby = []
    monkeypatch.setattr("przetargi.sources.base.time.sleep", lambda _: None)

    def licz(*a, **k):
        proby.append(1)
        return FalszywaOdpowiedz(404)

    monkeypatch.setattr(klient.session, "request", licz)
    with pytest.raises(SourceError, match="odrzucone"):
        klient.get_json("https://example.invalid")
    assert len(proby) == 1


def test_zmiana_regul_usuwa_wpisy_ktore_przestaly_pasowac(config, tmp_path, monkeypatch):
    """Zawężenie kategorii musi posprzątać także to, co już jest w bazie.

    Bez tego wpis zapisany pod starą regułą zostawałby w portalu na zawsze,
    bo przebieg klasyfikuje wyłącznie świeżo pobrane ogłoszenia.
    """
    monkeypatch.setattr("przetargi.pipeline.build_sources", lambda _: [ZrodloDzialajace()])

    store = TenderStore(tmp_path / "t.json")
    # Wpis, który nigdy nie pasowałby do żadnej kategorii, ale ma ją zapisaną.
    store.tenders["stary:1"] = Tender(
        id="stary:1", source="stary", native_id="1",
        title="Budowa mostu przez rzekę", buyer="Gmina Z",
        publication_date=REF.isoformat(), categories=["sprzatanie"],
    )
    raport, _ = run_update(config, store, REF)

    assert "stary:1" not in store.tenders
    assert raport.reclassified == 1


def test_przeklasyfikowanie_zachowuje_wpisy_nadal_pasujace(config, tmp_path, monkeypatch):
    monkeypatch.setattr("przetargi.pipeline.build_sources", lambda _: [ZrodloDzialajace()])

    store = TenderStore(tmp_path / "t.json")
    store.tenders["stary:2"] = Tender(
        id="stary:2", source="stary", native_id="2",
        title="Sprzątanie hali sportowej", buyer="Gmina Y",
        publication_date=REF.isoformat(), categories=[],
    )
    raport, _ = run_update(config, store, REF)

    assert "stary:2" in store.tenders
    # Kategoria zostaje uzupełniona przy okazji przeliczenia.
    assert store.tenders["stary:2"].categories == ["sprzatanie"]
    assert raport.reclassified == 0
