import datetime as dt

from przetargi.models import Tender
from przetargi.store import TenderStore

REF = dt.date(2026, 8, 31)


def _tender(tid, **kwargs):
    base = dict(
        id=tid,
        source=tid.split(":")[0],
        native_id=tid.split(":")[1],
        title="Sprzątanie biur",
        buyer="Gmina X",
        publication_date="2026-08-30",
    )
    base.update(kwargs)
    return Tender(**base)


def test_merge_dodaje_i_znakuje_date_pierwszego_widzenia(tmp_path):
    store = TenderStore(tmp_path / "t.json")
    report = store.merge([_tender("ted:1")], REF)
    assert report.added == 1
    assert store.tenders["ted:1"].first_seen == "2026-08-31"
    assert store.tenders["ted:1"].last_seen == "2026-08-31"


def test_merge_zachowuje_first_seen_przy_aktualizacji(tmp_path):
    store = TenderStore(tmp_path / "t.json")
    store.merge([_tender("ted:1")], REF)
    later = dt.date(2026, 9, 5)
    report = store.merge([_tender("ted:1", title="Nowy tytuł")], later)

    assert report.added == 0 and report.updated == 1
    assert store.tenders["ted:1"].first_seen == "2026-08-31"
    assert store.tenders["ted:1"].last_seen == "2026-09-05"
    assert store.tenders["ted:1"].title == "Nowy tytuł"


def test_puste_pole_ze_zrodla_nie_kasuje_danych(tmp_path):
    store = TenderStore(tmp_path / "t.json")
    store.merge([_tender("ted:1", description="Pełny opis", deadline="2026-09-20")], REF)
    store.merge([_tender("ted:1", description="", deadline=None)], REF)

    assert store.tenders["ted:1"].description == "Pełny opis"
    assert store.tenders["ted:1"].deadline == "2026-09-20"


def test_deduplikacja_scala_to_samo_zamowienie_z_dwoch_zrodel(tmp_path):
    store = TenderStore(tmp_path / "t.json")
    bogaty = _tender("ted:1", description="Opis", deadline="2026-09-20", value=1000.0)
    ubogi = _tender("bzp:9", url="https://bzp.example/9")
    report = store.merge([bogaty, ubogi], REF)

    assert report.merged == 1
    assert set(store.tenders) == {"ted:1"}
    assert store.tenders["ted:1"].extra_links[0]["url"] == "https://bzp.example/9"


def test_deduplikacja_nie_scala_roznych_lat(tmp_path):
    store = TenderStore(tmp_path / "t.json")
    store.merge(
        [
            _tender("bzp:1", publication_date="2025-08-30"),
            _tender("bzp:2", publication_date="2026-08-30"),
        ],
        REF,
    )
    assert len(store.tenders) == 2


def test_deduplikacja_nie_scala_roznych_zamawiajacych(tmp_path):
    store = TenderStore(tmp_path / "t.json")
    store.merge([_tender("bzp:1", buyer="Gmina A"), _tender("bzp:2", buyer="Gmina B")], REF)
    assert len(store.tenders) == 2


def test_prune_usuwa_po_terminie_ale_zostawia_swieze(tmp_path):
    store = TenderStore(tmp_path / "t.json")
    store.merge(
        [
            _tender("bzp:stary", buyer="A", deadline="2020-01-01"),
            _tender("bzp:swiezy", buyer="B", deadline="2026-09-20"),
        ],
        REF,
    )
    assert store.prune(120, REF) == 1
    assert set(store.tenders) == {"bzp:swiezy"}


def test_prune_uzywa_publikacji_gdy_brak_terminu(tmp_path):
    store = TenderStore(tmp_path / "t.json")
    store.merge([_tender("bzp:1", deadline=None, publication_date="2020-01-01")], REF)
    assert store.prune(120, REF) == 1


def test_zapis_i_odczyt_zachowuje_dane(tmp_path):
    path = tmp_path / "t.json"
    store = TenderStore(path)
    store.merge([_tender("ted:1", cpv=["90910000-9"], value=1234.5)], REF)
    store.touch()
    store.save()

    wczytany = TenderStore(path).load()
    assert wczytany.tenders["ted:1"] == store.tenders["ted:1"]
    assert wczytany.updated_at == store.updated_at


def test_uszkodzony_plik_nie_wywala_przebiegu(tmp_path):
    path = tmp_path / "t.json"
    path.write_text("{to nie jest json", encoding="utf-8")
    store = TenderStore(path).load()
    assert store.tenders == {}


def test_by_category_filtruje(tmp_path):
    store = TenderStore(tmp_path / "t.json")
    store.merge(
        [
            _tender("bzp:1", buyer="A", categories=["sprzatanie"]),
            _tender("bzp:2", buyer="B", categories=["catering"]),
        ],
        REF,
    )
    assert [t.id for t in store.by_category("catering")] == ["bzp:2"]
