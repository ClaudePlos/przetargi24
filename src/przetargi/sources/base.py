"""Wspólna warstwa dla źródeł danych: klient HTTP i kontrakt adaptera."""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Sequence

import requests

from ..config import Settings
from ..models import Tender

log = logging.getLogger(__name__)

USER_AGENT = (
    "Przetargi24/1.0 (+https://github.com/ClaudePlos/przetargi24) "
    "otwarty agregator ogloszen publicznych"
)

# Kody, które zwykle mijają po chwili — przy nich ponawiamy zapytanie.
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class SourceError(RuntimeError):
    """Źródło nie odpowiedziało poprawnie — przebieg trwa dalej bez niego."""


class HttpClient:
    """Cienka nakładka na requests: nagłówki, limity czasu i ponawianie."""

    def __init__(self, timeout: int = 60, retries: int = 3) -> None:
        self.timeout = timeout
        self.retries = max(1, retries)
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept": "application/json, text/xml;q=0.8, */*;q=0.5"}
        )

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                # Problem sieciowy — warto spróbować jeszcze raz.
                last_error = exc
            else:
                status = response.status_code
                if status < 400:
                    return response
                if status not in RETRYABLE_STATUS:
                    # 4xx nie minie samo: ponawianie tylko zjadłoby czas przebiegu.
                    raise SourceError(f"HTTP {status} z {url} — zapytanie odrzucone")
                last_error = SourceError(f"HTTP {status} z {url}")

            if attempt == self.retries:
                break
            # Wykładnicze wycofanie: 2 s, 4 s, 8 s...
            delay = 2**attempt
            log.warning(
                "Próba %s/%s dla %s nie powiodła się (%s) — ponawiam za %ss",
                attempt, self.retries, url, last_error, delay,
            )
            time.sleep(delay)
        raise SourceError(f"Nie udało się pobrać {url}: {last_error}") from last_error

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return _decode_json(self.request("GET", url, **kwargs), url)

    def post_json(self, url: str, **kwargs: Any) -> Any:
        return _decode_json(self.request("POST", url, **kwargs), url)

    def close(self) -> None:
        self.session.close()


def _decode_json(response: requests.Response, url: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        preview = response.text[:200].replace("\n", " ")
        raise SourceError(f"{url} zwrócił odpowiedź, która nie jest JSON-em: {preview!r}") from exc


@dataclass
class FetchContext:
    """Parametry jednego przebiegu pobierania, wspólne dla wszystkich źródeł."""

    settings: Settings
    date_from: dt.date
    date_to: dt.date
    http: HttpClient
    limit: int = 600


@dataclass
class SourceResult:
    """Wynik odpytania jednego źródła — trafia na stronę jako stan źródeł."""

    key: str
    label: str
    ok: bool
    fetched: int = 0
    error: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "ok": self.ok,
            "fetched": self.fetched,
            "error": self.error,
            "duration_seconds": round(self.duration_seconds, 2),
        }


class Source:
    """Kontrakt adaptera źródła.

    Adapter dostarcza `fetch()` zwracające surowe ogłoszenia jako `Tender`.
    Nie filtruje po kategoriach — tym zajmuje się `classify`.
    """

    key: str = ""
    label: str = ""
    homepage: str = ""
    enabled: bool = True

    def fetch(self, ctx: FetchContext) -> Iterator[Tender]:  # pragma: no cover - interfejs
        raise NotImplementedError


# --- pomocnicze wyciąganie wartości z nieprzewidywalnych struktur JSON -----
#
# Odpowiedzi API bywają zagnieżdżone i wielojęzyczne: to samo pole potrafi
# być napisem, listą napisów albo mapą {"pol": ["..."], "eng": ["..."]}.
# Poniższe funkcje sprowadzają każdy z tych kształtów do zwykłego tekstu,
# dzięki czemu zmiana kształtu odpowiedzi nie wywraca całego przebiegu.

PREFERRED_LANGUAGES = ("pol", "pl", "POL", "PL", "eng", "en")


def first_text(value: Any, languages: Sequence[str] = PREFERRED_LANGUAGES) -> str:
    """Wyciąga pierwszy sensowny napis z napisu, listy lub mapy językowej."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for lang in languages:
            if lang in value:
                text = first_text(value[lang], languages)
                if text:
                    return text
        for item in value.values():
            text = first_text(item, languages)
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple, set)):
        for item in value:
            text = first_text(item, languages)
            if text:
                return text
        return ""
    return str(value).strip()


def all_texts(value: Any, languages: Sequence[str] = PREFERRED_LANGUAGES) -> list[str]:
    """Spłaszcza zagnieżdżoną strukturę do listy niepustych napisów."""
    out: list[str] = []
    if value is None:
        return out
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, dict):
        for lang in languages:
            if lang in value:
                found = all_texts(value[lang], languages)
                if found:
                    return found
        for item in value.values():
            out.extend(all_texts(item, languages))
        return _dedupe(out)
    if isinstance(value, (list, tuple, set)):
        for item in value:
            out.extend(all_texts(item, languages))
        return _dedupe(out)
    return [str(value).strip()]


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


# Kod CPV to osiem cyfr, opcjonalnie z cyfrą kontrolną po myślniku.
_CPV_PATTERN = re.compile(r"(?<!\d)(\d{8})(?:-\d)?(?!\d)")


def extract_cpv_codes(value: Any, limit: int = 12) -> list[str]:
    """Wyciąga kody CPV z listy, mapy albo napisu z etykietami.

    BZP podaje wszystkie kody w jednym polu tekstowym razem z opisami,
    TED zwraca czystą listę — jedno wyrażenie obsługuje oba kształty.
    """
    kody: list[str] = []
    widziane: set[str] = set()
    for tekst in all_texts(value):
        for dopasowanie in _CPV_PATTERN.finditer(tekst):
            # Zachowujemy zapis z cyfrą kontrolną ("90910000-9") do wyświetlenia,
            # ale duplikaty rozpoznajemy po samych ośmiu cyfrach.
            if dopasowanie.group(1) not in widziane:
                widziane.add(dopasowanie.group(1))
                kody.append(dopasowanie.group(0))
    return kody[:limit]


def pick(data: dict[str, Any], *keys: str) -> Any:
    """Zwraca pierwszy niepusty klucz z listy — nazwy pól bywają różne."""
    for key in keys:
        if isinstance(data, dict) and data.get(key) not in (None, "", [], {}):
            return data[key]
    return None


def to_float(value: Any) -> float | None:
    """Zamienia '1 234,56 PLN' albo {'amount': 1234.56} na liczbę."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return to_float(pick(value, "amount", "value", "netAmount", "grossAmount"))
    if isinstance(value, (list, tuple)):
        for item in value:
            parsed = to_float(item)
            if parsed is not None:
                return parsed
        return None
    text = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


_KEY_NOISE = str.maketrans("", "", "-_ .")


def _norm_key(key: str) -> str:
    return str(key).translate(_KEY_NOISE).lower()


def pick_ci(data: Any, *keys: str) -> Any:
    """Jak `pick`, ale ignoruje wielkość liter i separatory w nazwie klucza.

    Dzięki temu 'PublicationDate', 'publication-date' i 'publicationDate'
    trafiają w to samo pole — a API bywa niekonsekwentne między wersjami.
    Obsługuje też ścieżki z kropką: pick_ci(row, "buyer.name").
    """
    if not isinstance(data, dict):
        return None
    index = {_norm_key(k): v for k, v in data.items()}
    for key in keys:
        if "." in key:
            value: Any = data
            for part in key.split("."):
                if not isinstance(value, dict):
                    value = None
                    break
                value = {_norm_key(k): v for k, v in value.items()}.get(_norm_key(part))
            if value not in (None, "", [], {}):
                return value
            continue
        value = index.get(_norm_key(key))
        if value not in (None, "", [], {}):
            return value
    return None


def dig(data: Any, path: str) -> Any:
    """Schodzi po ścieżce 'a.b.c' w zagnieżdżonym JSON-ie; '' zwraca całość."""
    if not path:
        return data
    value = data
    for part in path.split("."):
        if isinstance(value, dict):
            value = {_norm_key(k): v for k, v in value.items()}.get(_norm_key(part))
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value
