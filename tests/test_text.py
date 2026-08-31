from przetargi.text import excerpt, normalize, slugify, strip_diacritics


def test_normalize_usuwa_polskie_znaki_i_wielkosc_liter():
    assert normalize("Sprzątanie POMIESZCZEŃ") == "sprzatanie pomieszczen"
    assert normalize("ŻÓŁĆ Łódź") == "zolc lodz"


def test_normalize_sklada_biale_znaki():
    assert normalize("  a \n\t b  ") == "a b"


def test_normalize_pustych_wartosci():
    assert normalize(None) == ""
    assert normalize("") == ""


def test_strip_diacritics_zachowuje_dlugosc_slowa():
    assert strip_diacritics("łąka") == "laka"


def test_slugify():
    assert slugify("Zakład Gospodarki Komunalnej") == "zaklad-gospodarki-komunalnej"
    assert slugify("!!!", fallback="brak") == "brak"


def test_excerpt_tnie_na_granicy_slowa():
    text = "Kompleksowe sprzątanie budynków użyteczności publicznej wraz z myciem okien"
    result = excerpt(text, 40)
    assert result.endswith("…")
    assert len(result) <= 45
    assert not result[:-1].endswith(" ")


def test_excerpt_nie_tnie_krotkiego_tekstu():
    assert excerpt("Krótki opis", 100) == "Krótki opis"
