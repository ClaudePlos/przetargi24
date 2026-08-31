import pytest

from przetargi.config import ConfigError, load_categories, load_config, load_sources_config


def test_wczytuje_domyslne_kategorie(config):
    slugs = [c.slug for c in config.categories]
    assert "sprzatanie" in slugs and "catering" in slugs


def test_szablon_jest_pomijany(config):
    assert "moja-kategoria" not in [c.slug for c in config.categories]


def test_kategorie_sa_posortowane_wg_pola_order(config):
    orders = [c.order for c in config.categories]
    assert orders == sorted(orders)


def _zapisz(tmp_path, nazwa, tresc):
    katalog = tmp_path / "categories"
    katalog.mkdir(exist_ok=True)
    (katalog / nazwa).write_text(tresc, encoding="utf-8")
    return tmp_path


def test_brak_slow_i_cpv_to_blad(tmp_path):
    _zapisz(tmp_path, "pusta.yml", "slug: pusta\nname: Pusta\nmatch: {}\n")
    with pytest.raises(ConfigError, match="match.cpv"):
        load_categories(tmp_path)


def test_zduplikowany_slug_to_blad(tmp_path):
    _zapisz(tmp_path, "a.yml", "slug: ta-sama\nname: A\nmatch:\n  keywords: ['x']\n")
    _zapisz(tmp_path, "b.yml", "slug: ta-sama\nname: B\nmatch:\n  keywords: ['y']\n")
    with pytest.raises(ConfigError, match="jest już użyty"):
        load_categories(tmp_path)


def test_wylaczona_kategoria_znika(tmp_path):
    _zapisz(tmp_path, "wlaczona.yml", "slug: wlaczona\nname: A\nmatch:\n  keywords: ['x']\n")
    _zapisz(
        tmp_path,
        "wylaczona.yml",
        "slug: wylaczona\nname: B\nenabled: false\nmatch:\n  keywords: ['y']\n",
    )
    assert [c.slug for c in load_categories(tmp_path)] == ["wlaczona"]


def test_brak_kategorii_to_blad(tmp_path):
    (tmp_path / "categories").mkdir()
    with pytest.raises(ConfigError, match="żadnej włączonej kategorii"):
        load_categories(tmp_path)


def test_niepoprawny_yaml_to_czytelny_blad(tmp_path):
    _zapisz(tmp_path, "zla.yml", "slug: [niedomknięta\n")
    with pytest.raises(ConfigError, match="YAML"):
        load_categories(tmp_path)


def test_nowa_kategoria_dziala_bez_zmian_w_kodzie(tmp_path):
    """Główna obietnica portalu: kategorię dodaje się jednym plikiem YAML."""
    from przetargi.classify import classify
    from przetargi.models import Tender

    _zapisz(
        tmp_path,
        "ochrona.yml",
        "slug: ochrona\nname: Ochrona osób i mienia\n"
        "match:\n  cpv: ['7971']\n  keywords: ['ochron* fizyczn*', 'dozór mieni*']\n",
    )
    kategorie = load_categories(tmp_path)
    assert [c.slug for c in kategorie] == ["ochrona"]

    tender = Tender(
        id="x:1", source="x", native_id="1", title="Usługi ochrony fizycznej obiektu"
    )
    classify(tender, kategorie, load_config().settings)
    assert tender.categories == ["ochrona"]


def test_zrodla_wymagaja_sekcji_sources(tmp_path):
    (tmp_path / "sources.yml").write_text("cos: innego\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="sources"):
        load_sources_config(tmp_path)


def test_site_url_z_env_wygrywa(config, monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://przyklad.pl/")
    assert config.settings.site_url == "https://przyklad.pl"
