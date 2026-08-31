"""Przykładowe ogłoszenia — podgląd strony bez dostępu do sieci.

Używane przez `python -m przetargi demo` oraz przez testy i CI, żeby dało się
zbudować i obejrzeć portal, zanim automat pobierze prawdziwe dane.
Treści są fikcyjne, ale mają kształt rekordów zwracanych przez BZP i TED.
"""

from __future__ import annotations

import datetime as dt

from .models import KIND_NOTICE, KIND_PLAN, Tender, today

SAMPLES = [
    # (dni od dziś do publikacji, dni do terminu, źródło, rodzaj, tytuł,
    #  zamawiający, miasto, CPV, wartość, opis)
    (0, 24, "bzp", KIND_NOTICE,
     "Kompleksowe sprzątanie i utrzymanie czystości w budynkach Urzędu Miasta",
     "Urząd Miasta Gdyni", "Gdynia", ["90910000-9", "90919200-4"], 1_240_000.0,
     "Codzienne sprzątanie 6 budynków biurowych o łącznej powierzchni 14 500 m², "
     "mycie okien dwa razy w roku oraz zapewnienie środków higienicznych."),
    (0, 31, "ted", KIND_NOTICE,
     "Usługi cateringowe — przygotowanie i dowóz posiłków dla szkół podstawowych",
     "Miasto Stołeczne Warszawa — Dzielnica Wola", "Warszawa",
     ["55524000-9", "55523100-3"], 4_800_000.0,
     "Przygotowanie i dostarczanie ok. 2 300 obiadów dziennie do 11 szkół podstawowych "
     "przez cały rok szkolny, z uwzględnieniem diet eliminacyjnych."),
    (0, 12, "bzp", KIND_NOTICE,
     "Dostawa artykułów spożywczych do stołówki Domu Pomocy Społecznej",
     "Dom Pomocy Społecznej w Zamościu", "Zamość", ["15800000-6", "15500000-3"], 610_000.0,
     "Sukcesywne dostawy nabiału, pieczywa, mięsa i warzyw w podziale na 6 części."),
    (1, 18, "bzp", KIND_NOTICE,
     "Usługa sprzątania pomieszczeń szpitalnych wraz z transportem wewnętrznym",
     "Wojewódzki Szpital Zespolony w Kielcach", "Kielce",
     ["90911200-8", "90921000-9"], 8_900_000.0,
     "Utrzymanie czystości w strefach o różnym reżimie sanitarnym, dezynfekcja powierzchni "
     "wysokiego dotyku oraz obsługa transportu wewnętrznego przez 36 miesięcy."),
    (2, 45, "ted", KIND_PLAN,
     "Wstępne ogłoszenie informacyjne — utrzymanie czystości obiektów uczelni",
     "Politechnika Wrocławska", "Wrocław", ["90911200-8"], 12_000_000.0,
     "Zapowiedź postępowania na kompleksowe utrzymanie czystości w 28 budynkach "
     "kampusu; planowane wszczęcie w przyszłym kwartale."),
    (2, 9, "bzp", KIND_NOTICE,
     "Zimowe utrzymanie dróg gminnych — odśnieżanie i usuwanie śliskości",
     "Gmina Nowy Targ", "Nowy Targ", ["90620000-9", "90630000-2"], 780_000.0,
     "Odśnieżanie 142 km dróg gminnych oraz posypywanie mieszanką piaskowo-solną "
     "w sezonie zimowym, gotowość całodobowa."),
    (3, 27, "bzp", KIND_NOTICE,
     "Świadczenie usług żywienia pacjentów szpitala w systemie tacowym",
     "Samodzielny Publiczny Zakład Opieki Zdrowotnej w Rzeszowie", "Rzeszów",
     ["55321000-6", "55322000-3"], 6_450_000.0,
     "Całodobowe żywienie ok. 420 pacjentów dziennie z uwzględnieniem 14 rodzajów diet, "
     "dystrybucja w systemie tacowym do oddziałów."),
    (4, 21, "bzp_plany", KIND_PLAN,
     "Plan postępowań 2027 — usługi cateringowe na wydarzenia miejskie",
     "Urząd Miejski w Białymstoku", "Białystok", ["55520000-1"], 340_000.0,
     "Pozycja planu postępowań: obsługa cateringowa konferencji i uroczystości miejskich; "
     "przewidywany tryb podstawowy, wszczęcie w I kwartale."),
    (5, 15, "ted", KIND_NOTICE,
     "Usługi pralnicze wraz z dzierżawą bielizny szpitalnej",
     "Szpital Uniwersytecki w Krakowie", "Kraków", ["98310000-9", "98311000-6"], 5_200_000.0,
     "Pranie, dezynfekcja i naprawa bielizny szpitalnej wraz z dzierżawą asortymentu, "
     "odbiór i dostawa pięć razy w tygodniu."),
    (6, 38, "bzp", KIND_NOTICE,
     "Dostawa środków czystości i artykułów higienicznych",
     "Zakład Gospodarki Komunalnej w Ostrołęce", "Ostrołęka", ["39830000-9"], 290_000.0,
     "Sukcesywne dostawy profesjonalnych środków czystości, worków na odpady "
     "i artykułów higienicznych przez 24 miesiące."),
    (7, -3, "bzp", KIND_NOTICE,
     "Prowadzenie stołówki pracowniczej w siedzibie zamawiającego",
     "Regionalna Dyrekcja Lasów Państwowych w Toruniu", "Toruń", ["55510000-8"], 195_000.0,
     "Prowadzenie stołówki dla ok. 120 pracowników — postępowanie z terminem, który już minął, "
     "pokazane jako przykład archiwalnego wpisu."),
    (8, 52, "ted", KIND_PLAN,
     "Wstępne ogłoszenie informacyjne — dostawy żywności dla jednostek oświatowych",
     "Miasto Poznań", "Poznań", ["15000000-8", "15800000-6"], 9_700_000.0,
     "Zapowiedź wieloczęściowego postępowania na dostawy żywności dla przedszkoli "
     "i szkół prowadzonych przez miasto."),
    (9, 19, "bzp", KIND_NOTICE,
     "Sprzątanie terenów zewnętrznych i pielęgnacja zieleni osiedlowej",
     "Spółdzielnia Mieszkaniowa „Podlesie”", "Lublin", ["90610000-6", "90600000-3"], 460_000.0,
     "Zamiatanie chodników i parkingów, opróżnianie koszy, koszenie trawników "
     "na terenie 9 nieruchomości."),
    (11, 6, "bzp", KIND_NOTICE,
     "Dostawa posiłków profilaktycznych dla pracowników",
     "Miejskie Przedsiębiorstwo Wodociągów i Kanalizacji w Katowicach", "Katowice",
     ["55520000-1"], 128_000.0,
     "Dostawa posiłków regeneracyjnych dla pracowników zatrudnionych w warunkach "
     "szczególnie uciążliwych w sezonie jesienno-zimowym."),
]


def demo_tenders(reference: dt.date | None = None) -> list[Tender]:
    """Buduje listę przykładowych ogłoszeń względem podanej daty."""
    base = reference or today()
    tenders = []
    for index, sample in enumerate(SAMPLES, start=1):
        pub_offset, deadline_offset, source, kind, title, buyer, city, cpv, value, desc = sample
        native_id = f"DEMO-{index:03d}"
        tenders.append(
            Tender(
                id=f"{source}:{native_id}",
                source=source,
                native_id=native_id,
                title=title,
                url=f"https://example.invalid/ogloszenie/{native_id}",
                description=desc,
                buyer=buyer,
                location=city,
                cpv=list(cpv),
                kind=kind,
                publication_date=(base - dt.timedelta(days=pub_offset)).isoformat(),
                deadline=(base + dt.timedelta(days=deadline_offset)).isoformat(),
                value=value,
                currency="PLN",
            ).normalized()
        )
    return tenders
