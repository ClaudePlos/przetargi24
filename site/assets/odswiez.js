/* Przycisk „Przejrzyj rejestry teraz” na stronie stanu źródeł.
 *
 * Strona jest statyczna i publiczna, więc nie może zawierać sekretu — sama
 * z siebie nie odpyta rejestrów. Prosi o to GitHuba, uruchamiając workflow:
 *
 *   • bez tokenu  — otwiera zakładkę Actions, gdzie wystarczy jedno kliknięcie,
 *   • z tokenem   — woła API GitHuba wprost stąd i pokazuje postęp przebiegu.
 *
 * Token podaje sam użytkownik i zostaje wyłącznie w jego przeglądarce.
 */
(function () {
  "use strict";

  var panel = document.getElementById("odswiez-panel");
  if (!panel) return;

  var OWNER = panel.getAttribute("data-owner");
  var REPO = panel.getAttribute("data-repo");
  var WORKFLOW = panel.getAttribute("data-workflow");
  var KLUCZ = "przetargi24:token";
  var API = "https://api.github.com/repos/" + OWNER + "/" + REPO;

  var przycisk = document.getElementById("odswiez");
  var poleDni = document.getElementById("odswiez-dni");
  var status = document.getElementById("odswiez-status");
  var szczegoly = document.getElementById("odswiez-token");
  var poleKlucza = document.getElementById("odswiez-klucz");
  var linkReczny = document.getElementById("odswiez-recznie");

  /* Dostęp do localStorage potrafi rzucić wyjątkiem (tryb prywatny,
     zablokowane dane witryny), więc każdy odczyt i zapis jest osłonięty. */
  function czytajToken() {
    try { return window.localStorage.getItem(KLUCZ) || ""; } catch (e) { return ""; }
  }
  function zapiszToken(wartosc) {
    try {
      if (wartosc) window.localStorage.setItem(KLUCZ, wartosc);
      else window.localStorage.removeItem(KLUCZ);
      return true;
    } catch (e) { return false; }
  }

  function pokaz(tekst, rodzaj) {
    status.hidden = false;
    status.textContent = tekst;
    status.className = "status" + (rodzaj ? " " + rodzaj : "");
  }

  function naglowki(token) {
    return {
      "Accept": "application/vnd.github+json",
      "Authorization": "Bearer " + token,
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json"
    };
  }

  function opiszBlad(odpowiedz) {
    if (odpowiedz.status === 401) return "Token odrzucony — sprawdź, czy nie wygasł.";
    if (odpowiedz.status === 403) return "Token nie ma uprawnienia „Actions: Read and write”.";
    if (odpowiedz.status === 404) {
      return "Nie znaleziono workflow albo token nie obejmuje tego repozytorium.";
    }
    if (odpowiedz.status === 422) return "GitHub odrzucił parametry uruchomienia.";
    return "GitHub odpowiedział błędem " + odpowiedz.status + ".";
  }

  function uruchom(token) {
    var dni = (poleDni.value || "").trim();
    var dane = { ref: "main" };
    if (dni) dane.inputs = { lookback_days: dni };

    przycisk.disabled = true;
    pokaz("Proszę GitHuba o uruchomienie przebiegu…");

    fetch(API + "/actions/workflows/" + WORKFLOW + "/dispatches", {
      method: "POST",
      headers: naglowki(token),
      body: JSON.stringify(dane)
    }).then(function (odpowiedz) {
      if (odpowiedz.status !== 204) throw new Error(opiszBlad(odpowiedz));
      pokaz("Przebieg zakolejkowany. Śledzę postęp…");
      /* GitHub potrzebuje chwili, zanim przebieg pojawi się na liście. */
      setTimeout(function () { sledz(token, 0); }, 4000);
    }).catch(function (blad) {
      przycisk.disabled = false;
      pokaz(blad.message || "Nie udało się połączyć z GitHubem.", "fail");
    });
  }

  function sledz(token, proba) {
    if (proba > 40) {  /* ~5 minut przy odpytywaniu co 8 s */
      przycisk.disabled = false;
      pokaz("Przebieg trwa dłużej niż zwykle — sprawdź go w zakładce Actions.", "warn");
      return;
    }
    fetch(API + "/actions/runs?event=workflow_dispatch&per_page=1", {
      headers: naglowki(token)
    }).then(function (odpowiedz) {
      if (!odpowiedz.ok) throw new Error(opiszBlad(odpowiedz));
      return odpowiedz.json();
    }).then(function (dane) {
      var przebieg = (dane.workflow_runs || [])[0];
      if (!przebieg) return setTimeout(function () { sledz(token, proba + 1); }, 8000);

      if (przebieg.status !== "completed") {
        pokaz("Przebieg w toku… (" + przebieg.status + ")");
        return setTimeout(function () { sledz(token, proba + 1); }, 8000);
      }
      przycisk.disabled = false;
      if (przebieg.conclusion === "success") {
        pokaz("Gotowe. Strona przebuduje się w ciągu minuty — odśwież ją za chwilę.", "ok");
      } else {
        pokaz("Przebieg zakończył się wynikiem: " + przebieg.conclusion +
              ". Szczegóły w zakładce Actions.", "fail");
      }
    }).catch(function (blad) {
      przycisk.disabled = false;
      pokaz(blad.message || "Utraciłem kontakt z API GitHuba.", "fail");
    });
  }

  przycisk.addEventListener("click", function () {
    var token = czytajToken();
    if (!token) {
      /* Bez tokenu nie ma czym zawołać API — kierujemy do Actions. */
      szczegoly.open = true;
      pokaz("Brak tokenu w tej przeglądarce — otwieram zakładkę Actions.", "warn");
      window.open(linkReczny.href, "_blank", "noopener");
      return;
    }
    uruchom(token);
  });

  document.getElementById("odswiez-zapisz").addEventListener("click", function () {
    var wartosc = (poleKlucza.value || "").trim();
    if (!wartosc) return pokaz("Wklej token przed zapisaniem.", "warn");
    if (!zapiszToken(wartosc)) {
      return pokaz("Przeglądarka nie pozwala zapisać danych tej witryny.", "fail");
    }
    poleKlucza.value = "";
    pokaz("Token zapisany w tej przeglądarce. Przycisk uruchomi teraz przebieg wprost stąd.", "ok");
  });

  document.getElementById("odswiez-usun").addEventListener("click", function () {
    zapiszToken("");
    pokaz("Token usunięty. Przycisk znów będzie otwierał zakładkę Actions.", "ok");
  });

  if (czytajToken()) {
    pokaz("Token jest ustawiony — przycisk uruchomi przebieg bez opuszczania strony.");
  }
})();
