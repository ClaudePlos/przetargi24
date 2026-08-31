import datetime as dt

import pytest

from przetargi.models import KIND_PLAN, Tender, days_until, parse_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-08-31T10:00:00Z", "2026-08-31"),
        ("2026-08-31T10:00:00+02:00", "2026-08-31"),
        ("2026-08-31", "2026-08-31"),
        ("20260831", "2026-08-31"),
        ("31.08.2026", "2026-08-31"),
        (dt.date(2026, 8, 31), "2026-08-31"),
        (["", "2026-08-31"], "2026-08-31"),
        (None, None),
        ("", None),
        ("nie-data", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_days_until():
    reference = dt.date(2026, 8, 31)
    assert days_until("2026-09-10", reference) == 10
    assert days_until("2026-08-30", reference) == -1
    assert days_until(None, reference) is None


def _tender(**kwargs):
    base = dict(id="x:1", source="x", native_id="1", title="Tytuł")
    base.update(kwargs)
    return Tender(**base)


def test_is_open_uwzglednia_brak_terminu():
    reference = dt.date(2026, 8, 31)
    assert _tender(deadline="2026-09-01").is_open(reference)
    assert _tender(deadline="2026-08-31").is_open(reference)
    assert not _tender(deadline="2026-08-30").is_open(reference)
    # Brak terminu traktujemy jak wpis nadal aktualny.
    assert _tender(deadline=None).is_open(reference)


def test_is_new_tylko_dla_dzisiejszej_daty():
    reference = dt.date(2026, 8, 31)
    assert _tender(first_seen="2026-08-31").is_new(reference)
    assert not _tender(first_seen="2026-08-30").is_new(reference)
    assert not _tender(first_seen="").is_new(reference)


def test_normalized_czysci_pola():
    tender = _tender(
        title="  Sprzątanie\n biur ",
        cpv=["90910000-9", "", "  "],
        extra_links=[{"label": "a", "url": ""}, {"label": "b", "url": "https://x"}],
    )
    tender.normalized()
    assert tender.title == "Sprzątanie biur"
    assert tender.cpv == ["90910000-9"]
    assert tender.extra_links == [{"label": "b", "url": "https://x"}]


def test_roundtrip_serializacji():
    tender = _tender(kind=KIND_PLAN, cpv=["15800000-6"], value=1000.0)
    assert Tender.from_dict(tender.to_dict()) == tender


def test_from_dict_ignoruje_nieznane_pola():
    tender = Tender.from_dict({"id": "a", "source": "b", "native_id": "c", "title": "t", "xx": 1})
    assert tender.id == "a"
