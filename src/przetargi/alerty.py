"""Alerty e-mail o nowych ogłoszeniach — dopasowanie, treść i wysyłka.

Podział jest celowy: dopasowanie i budowa wiadomości to czyste funkcje, które
testujemy bez sieci. Rozmowa z Supabase i z usługą pocztową siedzi w cienkich
klasach, które w testach podmieniamy na atrapy.

Klucz serwisowy Supabase omija Row Level Security, więc żyje wyłącznie
w sekretach GitHub Actions — nigdy w stronie ani w repozytorium.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .classify import normalize_cpv
from .models import Tender
from .text import normalize

log = logging.getLogger(__name__)

# Ile ogłoszeń pokazujemy w jednym e-mailu, zanim dopiszemy „i N dalszych”.
LIMIT_W_MAILU = 15


@dataclass
class Alert:
    """Zapisany filtr użytkownika. Puste pole znaczy „bez ograniczenia”."""

    id: str
    email: str
    nazwa: str = "Mój alert"
    kategorie: list[str] = field(default_factory=list)
    frazy: list[str] = field(default_factory=list)
    cpv: list[str] = field(default_factory=list)
    wojewodztwa: list[str] = field(default_factory=list)
    wartosc_min: float | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Alert":
        """Buduje alert z wiersza zwróconego przez REST API Supabase."""
        profil = row.get("profile") or {}
        if isinstance(profil, list):  # zagnieżdżony select bywa listą
            profil = profil[0] if profil else {}
        return cls(
            id=str(row.get("id") or ""),
            email=str(profil.get("email") or row.get("email") or ""),
            nazwa=str(row.get("nazwa") or "Mój alert"),
            kategorie=list(row.get("kategorie") or []),
            frazy=list(row.get("frazy") or []),
            cpv=list(row.get("cpv") or []),
            wojewodztwa=list(row.get("wojewodztwa") or []),
            wartosc_min=row.get("wartosc_min"),
        )


def pasuje(alert: Alert, tender: Tender) -> bool:
    """Czy ogłoszenie spełnia wszystkie wypełnione warunki alertu.

    Warunki łączy koniunkcja: wypełnione pola muszą pasować wszystkie.
    Wewnątrz jednego pola wystarczy jedno trafienie z listy.
    """
    if alert.kategorie and not set(alert.kategorie) & set(tender.categories):
        return False

    if alert.frazy:
        tekst = normalize(tender.search_text())
        if not any(normalize(fraza) in tekst for fraza in alert.frazy if fraza.strip()):
            return False

    if alert.cpv:
        kody = [normalize_cpv(kod) for kod in tender.cpv]
        przedrostki = [normalize_cpv(p) for p in alert.cpv if p.strip()]
        if not any(k.startswith(p) for k in kody for p in przedrostki if k and p):
            return False

    if alert.wojewodztwa:
        miejsce = normalize(tender.location)
        if not any(normalize(w) in miejsce for w in alert.wojewodztwa if w.strip()):
            return False

    # Brak wartości nie dyskwalifikuje — wiele ogłoszeń jej nie podaje,
    # a odsiewanie ich po cichu ukrywałoby przed użytkownikiem realne szanse.
    if alert.wartosc_min is not None and tender.value is not None:
        if tender.value < float(alert.wartosc_min):
            return False

    return True


def dopasuj(alert: Alert, tenders: Iterable[Tender]) -> list[Tender]:
    """Ogłoszenia pasujące do alertu, najświeższe na początku."""
    trafione = [t for t in tenders if pasuje(alert, t)]
    return sorted(trafione, key=lambda t: t.sort_key(), reverse=True)


# --- treść wiadomości -----------------------------------------------------

def _termin(tender: Tender, dzis: dt.date | None = None) -> str:
    if not tender.deadline:
        return "termin nieokreślony"
    zostalo = tender.days_left(dzis)
    if zostalo is None:
        return tender.deadline
    if zostalo < 0:
        return f"{tender.deadline} (termin minął)"
    if zostalo == 0:
        return f"{tender.deadline} (dziś!)"
    return f"{tender.deadline} (za {zostalo} dni)"


def zbuduj_wiadomosc(
    alert: Alert,
    tenders: Sequence[Tender],
    adres_portalu: str = "",
    dzis: dt.date | None = None,
) -> tuple[str, str, str]:
    """Zwraca (temat, treść HTML, treść tekstowa) dla jednego alertu."""
    ile = len(tenders)
    slowo = "nowe ogłoszenie" if ile == 1 else "nowych ogłoszeń"
    # Imiesłów musi zgadzać się liczbą z rzeczownikiem, inaczej zdanie zgrzyta.
    pasujace = "pasujące" if ile == 1 else "pasujących"
    temat = f"Przetargi24: {ile} {slowo} — {alert.nazwa}"

    pokazane = list(tenders[:LIMIT_W_MAILU])
    reszta = ile - len(pokazane)

    wiersze_html, wiersze_tekst = [], []
    for tender in pokazane:
        tytul = html.escape(tender.title)
        link = html.escape(tender.url or adres_portalu, quote=True)
        meta = " · ".join(
            czesc for czesc in (
                html.escape(tender.buyer) if tender.buyer else "",
                _termin(tender, dzis),
            ) if czesc
        )
        wiersze_html.append(
            f'<li style="margin:0 0 14px"><a href="{link}" '
            f'style="color:#1d5fd0;text-decoration:none;font-weight:600">{tytul}</a>'
            f'<br><span style="color:#5b6572;font-size:14px">{meta}</span></li>'
        )
        wiersze_tekst.append(f"• {tender.title}\n  {meta}\n  {tender.url}")

    stopka_html = (
        f'<p style="color:#8a93a0;font-size:13px;margin-top:26px">'
        f'Alert „{html.escape(alert.nazwa)}”. '
        f'<a href="{html.escape(adres_portalu, quote=True)}/panel.html">Zmień lub wyłącz</a>'
        f" w panelu konta.</p>"
    )
    dopisek = f"\n\n…i {reszta} dalszych — pełna lista w portalu." if reszta > 0 else ""

    tresc_html = (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;'
        'max-width:640px;margin:0 auto">'
        f'<h2 style="font-size:19px;margin:0 0 4px">{ile} {slowo}</h2>'
        f'<p style="color:#5b6572;margin:0 0 18px">{pasujace} do alertu '
        f'„{html.escape(alert.nazwa)}”</p>'
        f'<ul style="list-style:none;padding:0;margin:0">{"".join(wiersze_html)}</ul>'
        + (f'<p style="color:#5b6572">…i {reszta} dalszych — pełna lista w portalu.</p>'
           if reszta > 0 else "")
        + stopka_html
        + "</div>"
    )
    tresc_tekst = (
        f"{ile} {slowo} {pasujace} do alertu „{alert.nazwa}”\n\n"
        + "\n\n".join(wiersze_tekst)
        + dopisek
        + f"\n\nZmień lub wyłącz alert: {adres_portalu}/panel.html"
    )
    return temat, tresc_html, tresc_tekst


# --- rozmowa z usługami zewnętrznymi --------------------------------------
#
# Cienkie nakładki na REST API. W testach podmieniamy je na atrapy, dzięki
# czemu cała logika wyżej jest sprawdzana bez sieci i bez kont.

class KlientSupabase:
    """Odczyt alertów i zapis dziennika wysyłek przez REST API Supabase."""

    def __init__(self, url: str, klucz_serwisowy: str, http: Any) -> None:
        self.url = url.rstrip("/")
        self.klucz = klucz_serwisowy
        self.http = http

    def _naglowki(self) -> dict[str, str]:
        return {
            "apikey": self.klucz,
            "Authorization": f"Bearer {self.klucz}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal,resolution=ignore-duplicates",
        }

    def aktywne_alerty(self) -> list[Alert]:
        """Alerty włączone przez użytkowników z opłaconym kontem.

        Filtr po planie jest tutaj, a nie w treści e-maila: konto darmowe
        ma alertów nie dostawać w ogóle, więc nie ma po co ich dopasowywać.
        """
        dane = self.http.get_json(
            f"{self.url}/rest/v1/alert",
            params={
                "select": "id,nazwa,kategorie,frazy,cpv,wojewodztwa,wartosc_min,"
                          "profile!inner(email,plan)",
                "aktywny": "eq.true",
                "profile.plan": "eq.premium",
            },
            headers=self._naglowki(),
        )
        return [Alert.from_row(row) for row in (dane or []) if isinstance(row, dict)]

    def juz_wyslane(self, alert_id: str) -> set[str]:
        dane = self.http.get_json(
            f"{self.url}/rest/v1/wyslane",
            params={"select": "ogloszenie", "alert": f"eq.{alert_id}"},
            headers=self._naglowki(),
        )
        return {str(r.get("ogloszenie")) for r in (dane or []) if isinstance(r, dict)}

    def zapisz_wyslane(self, alert_id: str, identyfikatory: Iterable[str]) -> None:
        wiersze = [{"alert": alert_id, "ogloszenie": oid} for oid in identyfikatory]
        if not wiersze:
            return
        self.http.post_json(
            f"{self.url}/rest/v1/wyslane", json=wiersze, headers=self._naglowki()
        )


class WysylkaResend:
    """Wysyłka e-maili przez Resend (https://resend.com)."""

    def __init__(self, klucz: str, nadawca: str, http: Any) -> None:
        self.klucz = klucz
        self.nadawca = nadawca
        self.http = http

    def wyslij(self, do: str, temat: str, tresc_html: str, tresc_tekst: str) -> None:
        self.http.post_json(
            "https://api.resend.com/emails",
            json={
                "from": self.nadawca,
                "to": [do],
                "subject": temat,
                "html": tresc_html,
                "text": tresc_tekst,
            },
            headers={
                "Authorization": f"Bearer {self.klucz}",
                "Content-Type": "application/json",
            },
        )


@dataclass
class RaportAlertow:
    alertow: int = 0
    wyslanych: int = 0
    ogloszen: int = 0
    bledow: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "alertow": self.alertow,
            "wyslanych": self.wyslanych,
            "ogloszen": self.ogloszen,
            "bledow": self.bledow,
        }


def wyslij_alerty(
    baza: KlientSupabase,
    poczta: WysylkaResend,
    nowe: Sequence[Tender],
    adres_portalu: str = "",
    dzis: dt.date | None = None,
) -> RaportAlertow:
    """Rozsyła alerty o nowych ogłoszeniach. Błąd jednego nie blokuje reszty."""
    raport = RaportAlertow()
    if not nowe:
        log.info("Brak nowych ogłoszeń — nie wysyłam alertów")
        return raport

    alerty = baza.aktywne_alerty()
    raport.alertow = len(alerty)
    log.info("Aktywnych alertów: %s, nowych ogłoszeń: %s", len(alerty), len(nowe))

    for alert in alerty:
        try:
            trafione = dopasuj(alert, nowe)
            if not trafione:
                continue
            # Ten sam przebieg może się powtórzyć w ciągu dnia — dziennik
            # pilnuje, żeby użytkownik nie dostał tego samego dwa razy.
            wyslane = baza.juz_wyslane(alert.id)
            swieze = [t for t in trafione if t.id not in wyslane]
            if not swieze:
                continue
            if not alert.email:
                log.warning("Alert %s bez adresu e-mail — pomijam", alert.id)
                continue

            temat, tresc_html, tresc_tekst = zbuduj_wiadomosc(
                alert, swieze, adres_portalu, dzis
            )
            poczta.wyslij(alert.email, temat, tresc_html, tresc_tekst)
            baza.zapisz_wyslane(alert.id, [t.id for t in swieze])

            raport.wyslanych += 1
            raport.ogloszen += len(swieze)
            log.info("Alert %s: wysłano %s ogłoszeń", alert.nazwa, len(swieze))
        except Exception as exc:  # noqa: BLE001 - jeden zły alert nie blokuje reszty
            raport.bledow += 1
            log.error("Alert %s zawiódł: %s", alert.id, exc)

    return raport
