# Przetargi24

Automatyczny portal z polskimi przetargami publicznymi. Działa w całości na
GitHubie: raz dziennie workflow pobiera świeże ogłoszenia z publicznych
rejestrów, przypisuje je do kategorii tematycznych, zapisuje w repozytorium
i publikuje statyczną stronę na GitHub Pages.

Startowe kategorie to **sprzątanie i utrzymanie czystości** oraz
**catering i żywienie**. Kolejne dodaje się jednym plikiem YAML — bez
dotykania kodu.

---

## Co dokładnie robi automat

Codziennie o 04:17 UTC (06:17 czasu polskiego latem) workflow
[`daily.yml`](.github/workflows/daily.yml):

1. odpytuje źródła o ogłoszenia z ostatnich 7 dni,
2. dopasowuje każde ogłoszenie do kategorii po kodach CPV i słowach kluczowych,
3. scala wynik z bazą w [`data/tenders.json`](data/tenders.json) — nowe wpisy
   dostają datę pierwszego zauważenia, znane są odświeżane, duplikaty z różnych
   źródeł łączone, a przeterminowane usuwane,
4. przelicza kategorie dla **całej** bazy, nie tylko dla świeżo pobranych
   ogłoszeń — dzięki temu zawężenie reguł w `config/categories/` sprząta także
   wpisy zapisane wcześniej i usuwa te, które przestały pasować,
5. zapisuje zmiany commitem do repozytorium,
6. generuje stronę i publikuje ją na GitHub Pages.

Zakres 7 dni przy dobowym cyklu jest celowy: gdy jeden przebieg się nie powiedzie,
następny nadrobi zaległość zamiast zostawić lukę.

### Co powstaje

| Adres | Zawartość |
| --- | --- |
| `/` | wszystkie ogłoszenia z wyszukiwarką i filtrami |
| `/kategoria/<slug>.html` | podstrona jednej kategorii |
| `/feed.xml`, `/kategoria/<slug>.xml` | kanały Atom (RSS) — także per kategoria |
| `/zrodla.html` | stan źródeł, podsumowanie przebiegu i przycisk odświeżania |
| `/dane/tenders.json` | surowe dane do własnych integracji |

Filtrowanie i wyszukiwanie działają po stronie przeglądarki, ale karty ogłoszeń
są w HTML-u — strona jest czytelna także z wyłączonym JavaScriptem i dla
wyszukiwarek.

---

## Uruchomienie u siebie

1. **Sforkuj lub skopiuj repozytorium.**
2. **Uruchom pierwszy przebieg:** zakładka _Actions → Codzienna aktualizacja
   przetargów → Run workflow_. Nie trzeba czekać do rana.
3. Strona pojawi się pod `https://<użytkownik>.github.io/<repozytorium>/`.

GitHub Pages włącza się samo przy pierwszym przebiegu — krok `configure-pages`
ma ustawione `enablement: true`. Gdyby to nie zadziałało, włącz je ręcznie:
_Settings → Pages → Build and deployment → Source: **GitHub Actions**_.

**W prywatnym repozytorium** publikacja strony wymaga planu GitHub Pro, Team
lub Enterprise; na planie darmowym Pages działa tylko dla repozytoriów
publicznych. Sama strona jest po opublikowaniu dostępna publicznie, nawet gdy
repozytorium pozostaje prywatne — a portal wystawia wyłącznie dane pochodzące
z jawnych rejestrów zamówień.

Workflow potrzebuje uprawnień do zapisu w repozytorium — jeśli push danych
albo włączenie Pages się nie powiedzie, sprawdź _Settings → Actions → General → Workflow permissions →
Read and write permissions_.

### Odświeżanie na żądanie

Poza harmonogramem automat uruchamia się na trzy sposoby:

1. **Przycisk „Przejrzyj rejestry teraz”** na stronie `/zrodla.html`.
2. _Actions → Codzienna aktualizacja przetargów → Run workflow_ (pole
   „Ile dni wstecz” pozwala nadrobić dłuższą przerwę).
3. Push do `main` zmieniający `config/**`, `site/**`, `src/**` lub sam workflow.

Strona jest statyczna i publiczna, więc **nie może zawierać sekretu** — sama
z siebie nie odpyta rejestrów. Przycisk domyślnie otwiera zakładkę Actions,
gdzie wystarczy jedno kliknięcie. Kto chce uruchamiać przebieg bez opuszczania
strony, wkleja w rozwijanym panelu własny
[token drobnoziarnisty](https://github.com/settings/personal-access-tokens/new)
ograniczony do tego repozytorium, z uprawnieniem `Actions: Read and write`.
Token zostaje w `localStorage` przeglądarki, nigdy nie trafia do repozytorium
ani do nikogo innego, a przycisk „Usuń token” kasuje go w każdej chwili.

---

## Dodawanie własnej kategorii

To jest podstawowy sposób rozbudowy portalu i **nie wymaga zmian w kodzie**.

```bash
cp config/categories/_szablon.yml config/categories/ochrona.yml
```

Uzupełnij plik:

```yaml
slug: ochrona                    # identyfikator w adresie URL
name: "Ochrona osób i mienia"
emoji: "🛡️"
order: 30                        # kolejność w menu, mniejsza liczba = wyżej
enabled: true
description: >-
  Usługi ochrony fizycznej, monitoringu i konwojowania wartości.

match:
  cpv:                           # przedrostki kodów CPV
    - "7971"                     # łapie 79710000, 79711000, 79713000...
  keywords:                      # frazy w tytule, opisie i nazwie zamawiającego
    - "ochron* fizyczn*"
    - "monitoring obiekt*"
    - "dozór mieni*"
  exclude_keywords:              # frazy dyskwalifikujące ogłoszenie
    - "ochrona danych osobowych"
    - "ochrona przeciwpożarowa"
  exclude_cpv:                   # kody dyskwalifikujące, też po przedrostku
    - "7972"                     # usługi śledcze
```

Commit i push wystarczą — najbliższy przebieg doda kategorię do menu, wygeneruje
jej podstronę i kanał RSS.

### Jak działa dopasowanie

Każde ogłoszenie dostaje punkty za trafienia:

* **kod CPV** — 3 punkty, dopasowanie po przedrostku (`"9091"` łapie `90910000-9`,
  `90911200-8`, `90919200-4`),
* **słowo kluczowe** — 2 punkty, szukane w tytule, opisie i nazwie zamawiającego.

Ogłoszenie trafia do kategorii przy wyniku ≥ 2 punkty (`classify.default_min_score`
w `config/settings.yml`, do nadpisania polem `min_score` w kategorii). Jedno
trafione słowo kluczowe wystarcza; kod CPV waży więcej, bo jest jednoznaczny.

**Wykluczenia mają pierwszeństwo przed wszystkim** — ogłoszenie pasujące do
`exclude_keywords` albo `exclude_cpv` nie trafi do kategorii, nawet gdy inny
kod CPV pasuje. Przykład z prawdziwych danych: kategoria „catering” obejmuje
cały dział CPV 15 (żywność), ale `exclude_cpv: ["157"]` odsiewa paszę dla
zwierząt.

Wykluczaj po CPV oszczędnie i wąsko. Wykluczenie całego działu potrafi
odciąć trafne ogłoszenia, które niosą taki kod pomocniczo — na przykład
usługa czyszczenia instalacji bywa opisana kodem 9091 razem z kodem
z działu 50 (naprawy).

### Pisanie słów kluczowych

Porównanie ignoruje wielkość liter i polskie znaki — `sprzatanie` znajdzie
`Sprzątanie`. Dopasowanie jest podłańcuchowe, a **gwiazdka zastępuje resztę
wyrazu**, co jest kluczowe przy polskiej odmianie:

| Zapis | Trafia | Nie trafia |
| --- | --- | --- |
| `sprzątanie` | „sprzątanie” | „sprzątania”, „sprzątaniem” |
| `sprzątan*` | „sprzątanie”, „sprzątania”, „sprzątaniem” | — |
| `czyszczeni* kanalizacj*` | „czyszczenie kanalizacji” | „czyszczenie okien i kanalizacji” |

Gwiazdka nie przeskakuje spacji, więc fraza dwuwyrazowa wymaga sąsiadujących
wyrazów. Dzięki temu wykluczenia nie odsiewają przypadkiem właściwych ogłoszeń.

Zmiana reguł działa wstecz: najbliższy przebieg przelicza kategorie dla całej
bazy, więc zawężenie listy słów usuwa też wpisy złapane wcześniej przez pomyłkę.

Po edycji warto sprawdzić konfigurację lokalnie:

```bash
python -m przetargi check
```

---

## Konta i alerty e-mail (opcjonalne)

Portal działa bez logowania. Konta włącza się, gdy chcesz wysyłać
**alerty e-mail** o nowych ogłoszeniach pasujących do zapisanego filtru.

### Dlaczego akurat tak

Strona jest statyczna i publiczna, więc nie ma serwera, który sprawdziłby
hasło. Logowanie robi Supabase: klucz `anon` w stronie jest **publiczny
z założenia**, a dostępu do danych pilnuje Row Level Security w bazie —
każde zapytanie z przeglądarki widzi wyłącznie wiersze zalogowanego
użytkownika. Klucz serwisowy, który omija RLS, żyje wyłącznie w sekretach
GitHub Actions i nigdy nie trafia do strony. Pilnują tego testy.

Plan konta ustawia wyłącznie webhook płatności, więc nie da się go podnieść
z przeglądarki. Limit alertów dla kont darmowych pilnuje wyzwalacz w bazie,
a nie interfejs — inaczej wystarczyłoby go ominąć.

### Uruchomienie

1. **Załóż projekt w [Supabase](https://supabase.com)** (darmowy plan wystarcza).
2. **Wklej schemat:** _SQL Editor → New query_ → cała zawartość
   [`supabase/schema.sql`](supabase/schema.sql) → Run.
3. **Wypełnij [`config/auth.yml`](config/auth.yml)** adresem projektu
   i kluczem `anon public` (_Settings → API_). To jedyne miejsce, gdzie
   klucz publiczny ma prawo się znaleźć.
4. **Dodaj sekrety** w _Settings → Secrets and variables → Actions_:

   | Sekret | Skąd |
   | --- | --- |
   | `SUPABASE_URL` | adres projektu Supabase |
   | `SUPABASE_SERVICE_KEY` | klucz `service_role` — **nigdy do repozytorium** |
   | `RESEND_API_KEY` | klucz z [Resend](https://resend.com) |
   | `ALERT_FROM` | adres nadawcy, np. `alerty@twojadomena.pl` |

5. **Płatności (opcjonalnie):** utwórz Payment Link w Stripe i wklej go
   w `premium.checkout_url`. Bez tego panel pokazuje informację „wkrótce”.

Dopóki sekretów brakuje, krok wysyłki w automacie kończy się powodzeniem
i tylko wypisuje, czego brakuje — codzienny przebieg pozostaje zielony.

### Jak działa wysyłka

Po każdym przebiegu automat bierze ogłoszenia zauważone **tego dnia**,
dopasowuje je do aktywnych alertów kont premium i wysyła jeden zbiorczy
e-mail na alert. Dziennik wysyłek w bazie pilnuje, żeby przy kilku
przebiegach dziennie nikt nie dostał tego samego ogłoszenia dwa razy.
Błąd jednego alertu nie blokuje pozostałych.

Ręcznie: `python -m przetargi alerty`.

---

## Źródła danych

Zdefiniowane w [`config/sources.yml`](config/sources.yml).

| Klucz | Co obejmuje |
| --- | --- |
| `ted` | TED — ogłoszenia unijne dla Polski, w tym wstępne ogłoszenia informacyjne (PIN), czyli przetargi zapowiadane z wyprzedzeniem |
| `bzp` | Biuletyn Zamówień Publicznych — krajowe postępowania poniżej progów unijnych |

Za „co się niedługo wydarzy” odpowiadają wstępne ogłoszenia informacyjne (PIN)
z TED — na stronie mają plakietkę **Plan postępowań** i osobny filtr.

Oba źródła pomijają ogłoszenia, które nie są okazją do złożenia oferty:
informacje o wyniku postępowania, o wykonaniu umowy i o jej zmianie. W TED
stanowią one blisko połowę polskich publikacji, więc odsiew zauważalnie
podnosi jakość listy.

Plany postępowań z BZP są pomijane świadomie: pod tym adresem wracają bez
tytułu, kodów CPV i terminu, więc nie ma czego pokazać ani po czym przypisać
kategorii.

Tablica e-Zamówień powiela też ogłoszenia unijne (numery serii S). Mamy je
już z TED — z opisem, terminem i wartością — więc są odsiewane wzorcem
`skip_id_pattern`, żeby nie dublowały wpisów.

BZP ma własne, dwudniowe okno (`lookback_days` w `config/sources.yml`).
Tablica e-Zamówień oddaje tylko 10 rekordów na żądanie i odpowiada wolno,
więc tygodniowy zakres oznaczałby setki żądań i kilkanaście minut przebiegu.
Przy codziennym uruchomieniu dwa dni dają zapas na jeden nieudany przebieg.

### Dodawanie i poprawianie źródeł

Poza adapterem TED (który ma własną składnię zapytań) źródła są **w pełni
sterowane YAML-em**. Zmiana adresu, sposobu stronicowania czy nazw pól
w odpowiedzi to edycja `config/sources.yml`, a nie kodu:

```yaml
  moje_zrodlo:
    type: json
    enabled: true
    label: "Nazwa pokazywana na stronie"
    kind: ogloszenie              # albo: plan
    url: "https://przyklad.pl/api/ogloszenia"
    method: POST                  # albo GET
    page_size: 50
    max_pages: 60                 # nadpisuje fetch.max_pages
    lookback_days: 2              # nadpisuje fetch.lookback_days
    result_path: "items"          # ścieżka do listy wyników w odpowiedzi
    body:                         # dla POST; dla GET użyj `params`
      PageNumber: "{page}"
      DataOd: "{date_from}"
    detail_url: "https://przyklad.pl/ogloszenie/{Id}"
    fields:                       # lista kandydatów na nazwę pola
      native_id: ["NoticeNumber", "Id"]
      title: ["OrderObject", "Name"]
      buyer: ["OrganizationName"]
      publication_date: ["PublicationDate"]
      deadline: ["SubmittingOffersDate"]
      cpv: ["CpvCode"]
    # Rodzaj wpisu z pola rekordu — gdy jeden adres zwraca i ogłoszenia,
    # i plany postępowań, i ogłoszenia o wyniku.
    kind_field: "noticeType"
    kind_map:
      TenderPlanNotice: plan
    skip_kinds:                   # rekordy pomijane w całości
      - ContractPerformingNotice
    skip_id_pattern: "^\\d{4}/S "  # wyrażenie odsiewające po identyfikatorze
```

Kody CPV wyciągane są wyrażeniem regularnym, więc działa zarówno czysta
lista (`["90910000"]`), jak i jeden napis z etykietami
(`"90910000-9 (Usługi sprzątania),90911300-9 (Usługi czyszczenia okien)"`).

Dostępne podstawienia: `{page}`, `{page_size}`, `{offset}`, `{date_from}`,
`{date_to}`, `{date_from_iso}`, `{date_to_iso}`.

Nazwy pól porównywane są bez wielkości liter i separatorów, więc
`PublicationDate`, `publication-date` i `publicationDate` znaczą to samo.
Obsługiwane są też ścieżki z kropką (`"buyer.name"`).

### Gdy źródło przestanie działać

Awaria jednego źródła **nie przerywa przebiegu** — pozostałe działają dalej,
a częściowo pobrane dane są zachowywane. Stan każdego źródła widać na stronie
`/zrodla.html` oraz w podsumowaniu zadania w zakładce Actions.

> **Uwaga o e-Zamówieniach.** Serwis nie publikuje wersjonowanej umowy API,
> więc adresy i nazwy pól dla `bzp` i `bzp_plany` mogą się zmienić bez
> zapowiedzi. Gdy któreś z nich zgłosi błąd na stronie „Stan źródeł”, poprawka
> sprowadza się do edycji `url`, `body` lub `fields` w `config/sources.yml`.
> Adapter TED opiera się na udokumentowanym API wyszukiwarki v3.

---

## Praca lokalna

```bash
pip install -e ".[dev]"

python -m przetargi check          # walidacja kategorii i źródeł
python -m przetargi demo --fresh   # przykładowe dane, bez sieci
python -m przetargi build          # generowanie strony do ./public
python -m pytest                   # testy

python -m http.server --directory public 8000   # podgląd na localhost:8000
```

Pełny przebieg z siecią:

```bash
python -m przetargi update         # pobranie i zapis do data/
python -m przetargi run            # pobranie + budowa strony
```

Przydatne przełączniki: `--config`, `--data`, `--output`, `-v` (szczegółowy log).
Zmienna `PRZETARGI_LOOKBACK_DAYS` nadpisuje zakres dni; przy ręcznym uruchomieniu
workflow można ją podać w formularzu.

---

## Ustawienia globalne

[`config/settings.yml`](config/settings.yml):

| Pole | Znaczenie | Domyślnie |
| --- | --- | --- |
| `fetch.lookback_days` | ile dni wstecz pobierać | 7 |
| `fetch.max_per_source` | limit ogłoszeń z jednego źródła na przebieg | 4000 |
| `fetch.max_pages` | limit stron na źródło | 45 |
| `fetch.timeout_seconds` / `fetch.retries` | limit czasu i liczba prób jednego żądania | 60 / 3 |
| `fetch.time_budget_seconds` | ile sekund wolno poświęcić jednemu źródłu | 240 |
| `store.retention_days` | po ilu dniach od terminu wpis znika | 120 |
| `classify.default_min_score` | próg przypisania do kategorii | 2 |

Błędy 5xx, 429 i problemy sieciowe są ponawiane z wycofaniem 2/4/8 s.
Odpowiedzi 4xx nie są ponawiane — nie miną same, a zjadłyby czas przebiegu.

Każde źródło ma własny budżet czasu. Po jego przekroczeniu pobieranie kończy
się, a przebieg używa tego, co zdążył zebrać — dzięki temu wolne API nie
rozciąga codziennego zadania na godziny. Ma to znaczenie przy BZP: tablica
e-Zamówień oddaje tylko 10 rekordów na żądanie i odpowiada z wyraźnym
opóźnieniem, więc to ona wyznacza długość przebiegu. Jeśli w portalu brakuje
krajowych ogłoszeń, podnieś `fetch.time_budget_seconds`.

---

## Struktura projektu

```
config/
  settings.yml            ustawienia globalne
  sources.yml             definicje źródeł danych
  categories/*.yml        kategorie (jeden plik = jedna kategoria)
src/przetargi/
  classify.py             dopasowanie CPV i słów kluczowych
  config.py               wczytywanie i walidacja YAML-i
  models.py               model ogłoszenia, parsowanie dat
  pipeline.py             przebieg aktualizacji
  render.py               generowanie strony
  store.py                baza JSON: scalanie, deduplikacja, retencja
  sources/                adaptery źródeł (ted.py, generic.py)
site/
  templates/*.html        szablony Jinja2
  assets/                 style i skrypt filtrowania
data/
  tenders.json            baza ogłoszeń (wersjonowana w gicie)
  status.json             stan ostatniego przebiegu
tests/                    120 testów
```

---

## Zakres i ograniczenia

* Portal ma charakter **informacyjny** — wiążąca jest zawsze treść ogłoszenia
  u zamawiającego. Dane pochodzą z publicznych rejestrów.
* Dopasowanie kategorii opiera się na kodach CPV i słowach kluczowych, więc
  bywa niedoskonałe. Precyzję poprawia się, dopisując frazy do `keywords`
  albo `exclude_keywords` w pliku kategorii.
* Wpisy znikają po `store.retention_days` od terminu składania ofert.
  Historia zmian pozostaje w gicie.

## Licencja

MIT
