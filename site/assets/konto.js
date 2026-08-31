/* Konta użytkowników i alerty — logowanie odnośnikiem e-mail przez Supabase.
 *
 * Klucz `anon` w atrybutach strony jest publiczny z założenia. Dostępu do
 * danych pilnuje Row Level Security w bazie: każde zapytanie stąd trafia
 * do bazy z tożsamością zalogowanego użytkownika i widzi wyłącznie jego
 * wiersze. Plan konta ustawia wyłącznie webhook płatności, kluczem
 * serwisowym — nie da się go podnieść z przeglądarki.
 */
(function () {
  "use strict";

  var korzen = document.getElementById("konto");
  if (!korzen) return;

  if (typeof window.supabase === "undefined") {
    /* Biblioteka ładuje się z CDN — gdy jest niedostępny, strona zostałaby
       na „Sprawdzam, czy jesteś zalogowany…” w nieskończoność. Lepiej
       powiedzieć wprost, co się stało. */
    var ladowanie = document.getElementById("ladowanie");
    if (ladowanie) {
      ladowanie.querySelector(".body").innerHTML =
        '<p class="status fail">Nie udało się wczytać biblioteki logowania. ' +
        "Sprawdź połączenie i odśwież stronę — jeśli problem wraca, " +
        "prawdopodobnie blokuje ją wtyczka do prywatności.</p>";
    }
    return;
  }

  var klient = window.supabase.createClient(
    korzen.getAttribute("data-supabase-url"),
    korzen.getAttribute("data-supabase-key")
  );
  var adresPlatnosci = korzen.getAttribute("data-checkout");

  var el = function (id) { return document.getElementById(id); };

  function pokazSekcje(ktora) {
    ["ladowanie", "logowanie", "zalogowany"].forEach(function (id) {
      el(id).hidden = id !== ktora;
    });
  }

  function status(pole, tekst, rodzaj) {
    pole.hidden = false;
    pole.textContent = tekst;
    pole.className = "status" + (rodzaj ? " " + rodzaj : "");
  }

  function wartosciZPola(id) {
    return (el(id).value || "")
      .split(",")
      .map(function (x) { return x.trim(); })
      .filter(Boolean);
  }

  // --- logowanie ----------------------------------------------------------

  el("wyslij-link").addEventListener("click", function () {
    var email = (el("email").value || "").trim();
    var pole = el("status-logowania");
    if (!email) return status(pole, "Podaj adres e-mail.", "warn");

    el("wyslij-link").disabled = true;
    klient.auth
      .signInWithOtp({ email: email, options: { emailRedirectTo: window.location.href } })
      .then(function (wynik) {
        el("wyslij-link").disabled = false;
        if (wynik.error) throw wynik.error;
        status(pole, "Sprawdź skrzynkę — wysłaliśmy odnośnik do logowania.", "ok");
      })
      .catch(function (blad) {
        el("wyslij-link").disabled = false;
        status(pole, blad.message || "Nie udało się wysłać odnośnika.", "fail");
      });
  });

  el("wyloguj").addEventListener("click", function () {
    klient.auth.signOut().then(function () { window.location.reload(); });
  });

  // --- profil i alerty ----------------------------------------------------

  function wczytajProfil(uzytkownik) {
    el("moj-email").textContent = uzytkownik.email;
    return klient
      .from("profile")
      .select("plan, premium_do")
      .eq("id", uzytkownik.id)
      .maybeSingle()
      .then(function (wynik) {
        var plan = (wynik.data && wynik.data.plan) || "free";
        var znacznik = el("moj-plan");
        znacznik.textContent = plan;
        znacznik.className = "pill " + (plan === "premium" ? "ok" : "fail");

        // Zachętę do płatności pokazujemy tylko kontom darmowym.
        el("panel-premium").hidden = plan === "premium";
        if (plan !== "premium") {
          if (adresPlatnosci) {
            el("kup").href = adresPlatnosci;
            el("kup").hidden = false;
          } else {
            el("brak-platnosci").hidden = false;
          }
        }
        return plan;
      });
  }

  function opiszAlert(alert) {
    var czesci = [];
    if (alert.kategorie && alert.kategorie.length) czesci.push(alert.kategorie.join(", "));
    if (alert.frazy && alert.frazy.length) czesci.push("frazy: " + alert.frazy.join(", "));
    if (alert.cpv && alert.cpv.length) czesci.push("CPV: " + alert.cpv.join(", "));
    if (alert.wojewodztwa && alert.wojewodztwa.length) {
      czesci.push("region: " + alert.wojewodztwa.join(", "));
    }
    if (alert.wartosc_min) czesci.push("od " + alert.wartosc_min + " zł");
    return czesci.join(" · ") || "bez ograniczeń";
  }

  function wczytajAlerty() {
    var lista = el("lista-alertow");
    return klient
      .from("alert")
      .select("id, nazwa, kategorie, frazy, cpv, wojewodztwa, wartosc_min, aktywny")
      .order("utworzono", { ascending: false })
      .then(function (wynik) {
        if (wynik.error) throw wynik.error;
        var alerty = wynik.data || [];
        if (!alerty.length) {
          lista.innerHTML = "<p>Nie masz jeszcze żadnego alertu.</p>";
          return;
        }
        lista.innerHTML = "";
        alerty.forEach(function (alert) {
          var wiersz = document.createElement("div");
          wiersz.className = "row";
          wiersz.style.justifyContent = "space-between";

          var opis = document.createElement("div");
          // textContent, a nie innerHTML — nazwa pochodzi od użytkownika.
          var mocny = document.createElement("b");
          mocny.textContent = alert.nazwa;
          opis.appendChild(mocny);
          opis.appendChild(document.createElement("br"));
          var drobne = document.createElement("span");
          drobne.style.color = "var(--text-muted)";
          drobne.style.fontSize = "14px";
          drobne.textContent = opiszAlert(alert) + (alert.aktywny ? "" : " · wyłączony");
          opis.appendChild(drobne);

          var usun = document.createElement("button");
          usun.type = "button";
          usun.className = "btn btn-ghost";
          usun.textContent = "Usuń";
          usun.addEventListener("click", function () {
            klient.from("alert").delete().eq("id", alert.id).then(wczytajAlerty);
          });

          wiersz.appendChild(opis);
          wiersz.appendChild(usun);
          lista.appendChild(wiersz);
        });
      })
      .catch(function (blad) {
        lista.innerHTML = "";
        var p = document.createElement("p");
        p.className = "status fail";
        p.textContent = blad.message || "Nie udało się wczytać alertów.";
        lista.appendChild(p);
      });
  }

  el("dodaj-alert").addEventListener("click", function () {
    var pole = el("status-alertu");
    var wybrane = Array.prototype.slice
      .call(el("a-kategorie").selectedOptions)
      .map(function (o) { return o.value; });
    var wartosc = parseFloat(el("a-wartosc").value);

    klient.auth.getUser().then(function (wynik) {
      var uzytkownik = wynik.data && wynik.data.user;
      if (!uzytkownik) return status(pole, "Sesja wygasła — zaloguj się ponownie.", "warn");

      klient
        .from("alert")
        .insert({
          uzytkownik: uzytkownik.id,
          nazwa: (el("a-nazwa").value || "").trim() || "Mój alert",
          kategorie: wybrane,
          frazy: wartosciZPola("a-frazy"),
          cpv: wartosciZPola("a-cpv"),
          wojewodztwa: wartosciZPola("a-region"),
          wartosc_min: isNaN(wartosc) ? null : wartosc
        })
        .then(function (odpowiedz) {
          if (odpowiedz.error) throw odpowiedz.error;
          status(pole, "Alert zapisany.", "ok");
          el("a-nazwa").value = "";
          wczytajAlerty();
        })
        .catch(function (blad) {
          // Limit kont darmowych pilnuje baza — komunikat przychodzi stamtąd.
          status(pole, blad.message || "Nie udało się zapisać alertu.", "fail");
        });
    });
  });

  // --- start --------------------------------------------------------------

  klient.auth.getSession().then(function (wynik) {
    var sesja = wynik.data && wynik.data.session;
    if (!sesja) return pokazSekcje("logowanie");
    pokazSekcje("zalogowany");
    wczytajProfil(sesja.user).then(wczytajAlerty);
  });

  klient.auth.onAuthStateChange(function (zdarzenie, sesja) {
    if (zdarzenie === "SIGNED_IN" && sesja) {
      pokazSekcje("zalogowany");
      wczytajProfil(sesja.user).then(wczytajAlerty);
    }
  });
})();
