import pytest

from przetargi.classify import classify, normalize_cpv, score_category
from przetargi.models import Tender


def _tender(title, cpv=(), description=""):
    return Tender(
        id="x:1", source="x", native_id="1", title=title, cpv=list(cpv), description=description
    )


@pytest.mark.parametrize(
    "raw,expected",
    [("90910000-9", "90910000"), ("90910000", "90910000"), ("153", "153"), ("9091", "9091")],
)
def test_normalize_cpv(raw, expected):
    assert normalize_cpv(raw) == expected


@pytest.mark.parametrize(
    "title,cpv,expected",
    [
        ("Kompleksowe sprzątanie pomieszczeń biurowych", ["90911200-8"], ["sprzatanie"]),
        ("Sprzątanie i utrzymanie czystości w urzędzie", [], ["sprzatanie"]),
        ("Odśnieżanie dróg powiatowych", ["90620000-9"], ["sprzatanie"]),
        ("Dostawa artykułów spożywczych do stołówki", ["15800000-6"], ["catering"]),
        ("Świadczenie usług cateringowych dla przedszkola", [], ["catering"]),
        ("Przygotowanie i dowóz posiłków dla uczniów", [], ["catering"]),
        ("Budowa drogi gminnej nr 4", ["45233120-6"], []),
        ("Zakup energii elektrycznej", ["09310000-5"], []),
    ],
)
def test_dopasowanie_kategorii(config, title, cpv, expected):
    tender = _tender(title, cpv)
    classify(tender, config.categories, config.settings)
    assert tender.categories == expected


@pytest.mark.parametrize(
    "title,cpv",
    [
        # Odmiana wyrazu nie może omijać wykluczenia.
        ("Dostawa preparatów do żywienia dojelitowego", ["15800000-6"]),
        ("Zakup karmy dla zwierząt w schronisku", ["15800000-6"]),
        ("Usługa czyszczenia kanalizacji deszczowej", ["90910000-9"]),
        ("Czyszczenie kotłów w kotłowni miejskiej", ["90910000-9"]),
    ],
)
def test_wykluczenia_maja_pierwszenstwo_przed_cpv(config, title, cpv):
    tender = _tender(title, cpv)
    classify(tender, config.categories, config.settings)
    assert tender.categories == []


def test_gwiazdka_nie_przeskakuje_spacji(config):
    """'czyszczeni* kanalizacj*' nie może wykluczyć niepowiązanego ogłoszenia."""
    tender = _tender("Czyszczenie okien oraz przeglądy kanalizacji", ["90911300-9"])
    classify(tender, config.categories, config.settings)
    assert "sprzatanie" in tender.categories


def test_cpv_liczy_sie_wyzej_niz_slowo_kluczowe(config):
    sprzatanie = config.category("sprzatanie")
    z_cpv = score_category(_tender("Usługa", ["90910000-9"]), sprzatanie, config.settings)
    ze_slowem = score_category(_tender("Sprzątanie"), sprzatanie, config.settings)
    assert z_cpv > ze_slowem > 0


def test_wpis_moze_trafic_do_kilku_kategorii(config):
    tender = _tender(
        "Sprzątanie stołówki szkolnej wraz z przygotowaniem posiłków",
        ["90911200-8", "55524000-9"],
    )
    classify(tender, config.categories, config.settings)
    assert set(tender.categories) == {"sprzatanie", "catering"}
    # Kolejność wg trafności — najwyższy wynik pierwszy.
    assert tender.scores[tender.categories[0]] >= tender.scores[tender.categories[1]]


def test_opis_tez_jest_przeszukiwany(config):
    tender = _tender("Usługa dla jednostki", description="Zakres obejmuje sprzątanie korytarzy.")
    classify(tender, config.categories, config.settings)
    assert tender.categories == ["sprzatanie"]
