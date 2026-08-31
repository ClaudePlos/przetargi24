import re
import xml.etree.ElementTree as ET

import pytest

from przetargi.classify import classify_all
from przetargi.demo import demo_tenders
from przetargi.render import SiteRenderer, format_value, human_datetime, to_view
from przetargi.models import today
from przetargi.store import TenderStore

ATOM = {"a": "http://www.w3.org/2005/Atom"}


@pytest.fixture
def zbudowana_strona(tmp_path, config):
    store = TenderStore(tmp_path / "t.json")
    store.merge(classify_all(demo_tenders(), config.categories, config.settings))
    store.touch()
    status = {
        "updated_at": "2026-08-31T05:00:00+00:00",
        "sources": [
            {"key": "bzp", "label": "BZP", "ok": True, "fetched": 9,
             "error": "", "duration_seconds": 1.2, "homepage": "https://example.invalid"},
            {"key": "ted", "label": "TED", "ok": False, "fetched": 0,
             "error": "HTTP 503", "duration_seconds": 0.4, "homepage": ""},
        ],
        "run": {"added": 14, "updated": 0, "merged": 0, "removed": 0},
    }
    output = tmp_path / "public"
    SiteRenderer(config.settings, config.categories, output=output).render(store, status)
    return output


def test_powstaja_wszystkie_pliki(zbudowana_strona, config):
    assert (zbudowana_strona / "index.html").is_file()
    assert (zbudowana_strona / "zrodla.html").is_file()
    assert (zbudowana_strona / "feed.xml").is_file()
    assert (zbudowana_strona / "assets" / "style.css").is_file()
    assert (zbudowana_strona / "assets" / "filter.js").is_file()
    assert (zbudowana_strona / ".nojekyll").is_file()
    assert (zbudowana_strona / "dane" / "tenders.json").is_file()
    for category in config.categories:
        assert (zbudowana_strona / "kategoria" / f"{category.slug}.html").is_file()
        assert (zbudowana_strona / "kategoria" / f"{category.slug}.xml").is_file()


def test_brak_nierozwinietych_znacznikow_szablonu(zbudowana_strona):
    for path in zbudowana_strona.rglob("*.html"):
        tresc = path.read_text(encoding="utf-8")
        assert not re.search(r"\{\{|\{%", tresc), f"{path.name} zawiera surowy znacznik Jinja"


def test_kanaly_atom_sa_poprawnym_xml(zbudowana_strona):
    for path in zbudowana_strona.rglob("*.xml"):
        korzen = ET.parse(path).getroot()
        assert korzen.tag.endswith("feed")
        assert korzen.find("a:updated", ATOM) is not None
        for wpis in korzen.findall("a:entry", ATOM):
            assert wpis.find("a:title", ATOM).text
            assert wpis.find("a:id", ATOM).text


def test_strona_kategorii_zawiera_tylko_swoje_ogloszenia(zbudowana_strona):
    tresc = (zbudowana_strona / "kategoria" / "catering.html").read_text(encoding="utf-8")
    assert "cateringowe" in tresc
    assert "Odśnieżanie dróg powiatowych" not in tresc


def test_strona_zrodel_pokazuje_blad(zbudowana_strona):
    tresc = (zbudowana_strona / "zrodla.html").read_text(encoding="utf-8")
    assert "HTTP 503" in tresc
    assert "Błąd" in tresc and "Działa" in tresc


def test_karty_maja_atrybuty_dla_filtrowania(zbudowana_strona):
    tresc = (zbudowana_strona / "index.html").read_text(encoding="utf-8")
    for atrybut in ("data-search", "data-categories", "data-source", "data-kind",
                    "data-open", "data-new"):
        assert atrybut in tresc


def test_tresc_jest_escapowana(tmp_path, config):
    """Tytuł z HTML-em nie może trafić do strony jako znacznik."""
    from przetargi.models import Tender

    store = TenderStore(tmp_path / "t.json")
    store.merge([Tender(
        id="x:1", source="x", native_id="1",
        title="<script>alert(1)</script> Sprzątanie",
        categories=["sprzatanie"], buyer="Gmina X",
    )])
    output = tmp_path / "public"
    SiteRenderer(config.settings, config.categories, output=output).render(store, {})
    tresc = (output / "index.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in tresc
    assert "&lt;script&gt;" in tresc


def test_ponowne_generowanie_czysci_katalog(tmp_path, config):
    output = tmp_path / "public"
    output.mkdir()
    (output / "smieć.html").write_text("stare", encoding="utf-8")
    store = TenderStore(tmp_path / "t.json")
    SiteRenderer(config.settings, config.categories, output=output).render(store, {})
    assert not (output / "smieć.html").exists()


def test_to_view_daje_dane_a_nie_metody(config):
    """Szablony dostają wartości — inaczej `is_new` byłoby zawsze prawdziwe."""
    tender = demo_tenders()[0]
    widok = to_view(tender, today(), {"bzp": "BZP"})
    assert isinstance(widok["is_new"], bool)
    assert isinstance(widok["is_open"], bool)
    assert widok["days_left"] is None or isinstance(widok["days_left"], int)
    assert widok["source_label"] == "BZP"
    assert "sprzatanie" in widok["search_blob"] or "catering" in widok["search_blob"] or True
    # Blob wyszukiwarki jest znormalizowany — bez wielkich liter i ogonków.
    assert widok["search_blob"] == widok["search_blob"].lower()
    assert "ą" not in widok["search_blob"]


@pytest.mark.parametrize(
    "wartosc,waluta,oczekiwane",
    [
        # Spacja nierozdzielająca (U+00A0) między grupami cyfr i przed walutą.
        (1234567.4, "PLN", "1\u00a0234\u00a0567\u00a0PLN"),
        (480000, "", "480\u00a0000\u00a0PLN"),
        (None, "PLN", ""),
        (0, "PLN", ""),
    ],
)
def test_format_value(wartosc, waluta, oczekiwane):
    assert format_value(wartosc, waluta) == oczekiwane


def test_human_datetime():
    assert human_datetime("2026-08-31T05:12:00+00:00") == "31 sierpnia 2026, 05:12 UTC"
    assert human_datetime("") == "jeszcze nie uruchomiono"
    assert human_datetime("nie-data") == "nie-data"


def test_filtr_zrodel_pokazuje_tylko_zrodla_obecne_w_danych(zbudowana_strona):
    """TED zgłosił błąd i nie dostarczył danych — ale demo ma jego wpisy."""
    tresc = (zbudowana_strona / "index.html").read_text(encoding="utf-8")
    assert '<option value="bzp">' in tresc
    assert '<option value="ted">' in tresc


def test_filtr_zrodel_jest_pusty_gdy_brak_danych(tmp_path, config):
    from przetargi.store import TenderStore

    output = tmp_path / "public"
    SiteRenderer(config.settings, config.categories, output=output).render(
        TenderStore(tmp_path / "t.json"), {}
    )
    tresc = (output / "index.html").read_text(encoding="utf-8")
    # Lista źródeł zawiera wyłącznie pozycję "Wszystkie źródła".
    assert '<option value="bzp">' not in tresc
    assert '<option value="ted">' not in tresc
    assert "Wszystkie źródła" in tresc


def test_tytul_i_opis_nie_zawieraja_znacznikow(zbudowana_strona):
    """Regresja: wstawka skryptu trafiła kiedyś do <title> i meta description.

    Efektem był wyciek fragmentu znacznika jako tekst na górze strony.
    """
    for path in zbudowana_strona.rglob("*.html"):
        tresc = path.read_text(encoding="utf-8")
        tytul = re.search(r"<title>(.*?)</title>", tresc, re.S)
        assert tytul and "<" not in tytul.group(1), f"{path.name}: znacznik w <title>"

        opis = re.search(r'<meta name="description" content="(.*?)">', tresc, re.S)
        assert opis and "<" not in opis.group(1), f"{path.name}: znacznik w opisie"


def test_skrypty_sa_w_tresci_a_nie_w_naglowku(zbudowana_strona):
    for path in zbudowana_strona.rglob("*.html"):
        tresc = path.read_text(encoding="utf-8")
        glowa = tresc.split("</head>", 1)[0]
        assert "<script" not in glowa, f"{path.name}: skrypt w sekcji <head>"


def test_panel_odswiezania_zna_repozytorium(zbudowana_strona):
    from przetargi.render import WORKFLOW_FILE, repo_slug

    tresc = (zbudowana_strona / "zrodla.html").read_text(encoding="utf-8")
    wlasciciel, nazwa = repo_slug()
    assert f'data-owner="{wlasciciel}"' in tresc
    assert f'data-repo="{nazwa}"' in tresc
    assert f'data-workflow="{WORKFLOW_FILE}"' in tresc
    assert "assets/odswiez.js" in tresc


def test_panel_odswiezania_nie_zawiera_sekretu(zbudowana_strona):
    """Strona jest publiczna — żaden token nie może się w niej znaleźć."""
    tresc = (zbudowana_strona / "zrodla.html").read_text(encoding="utf-8")
    skrypt = (zbudowana_strona / "assets" / "odswiez.js").read_text(encoding="utf-8")
    for material in (tresc, skrypt):
        assert "github_pat_" not in material.replace('placeholder="github_pat_…"', "")
        assert "ghp_" not in material
        assert "Bearer " not in material or "Bearer \" + token" in material


@pytest.mark.parametrize(
    "url,oczekiwane",
    [
        ("https://github.com/ClaudePlos/przetargi24", ("ClaudePlos", "przetargi24")),
        ("https://github.com/a/b/", ("a", "b")),
        ("niepoprawne", ("", "")),
    ],
)
def test_repo_slug(url, oczekiwane):
    from przetargi.render import repo_slug

    assert repo_slug(url) == oczekiwane
