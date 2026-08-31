/* Filtrowanie listy ogłoszeń po stronie przeglądarki.
   Karty są w HTML-u, więc strona działa też bez JavaScriptu — skrypt
   jedynie ukrywa te, które nie pasują do wybranych filtrów. */
(function () {
  "use strict";

  var cards = Array.prototype.slice.call(document.querySelectorAll("#cards .card"));
  if (!cards.length) return;

  var q = document.getElementById("q");
  var fCategory = document.getElementById("f-category");
  var fSource = document.getElementById("f-source");
  var fKind = document.getElementById("f-kind");
  var fOpen = document.getElementById("f-open");
  var fNew = document.getElementById("f-new");
  var counter = document.getElementById("result-count");
  var noResults = document.getElementById("no-results");

  /* Ta sama normalizacja co po stronie generatora: bez wielkości liter
     i bez polskich znaków, żeby "sprzatanie" znajdowało "sprzątanie". */
  function normalize(value) {
    return (value || "")
      .toLowerCase()
      .replace(/ł/g, "l")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function value(el) { return el ? el.value : ""; }

  function apply() {
    var terms = normalize(value(q)).split(/\s+/).filter(Boolean);
    var category = value(fCategory);
    var source = value(fSource);
    var kind = value(fKind);
    var onlyOpen = fOpen && fOpen.checked;
    var onlyNew = fNew && fNew.checked;
    var visible = 0;

    cards.forEach(function (card) {
      var haystack = card.getAttribute("data-search") || "";
      var show =
        (!category || (card.getAttribute("data-categories") || "").split(" ").indexOf(category) !== -1) &&
        (!source || card.getAttribute("data-source") === source) &&
        (!kind || card.getAttribute("data-kind") === kind) &&
        (!onlyOpen || card.getAttribute("data-open") === "1") &&
        (!onlyNew || card.getAttribute("data-new") === "1") &&
        terms.every(function (term) { return haystack.indexOf(term) !== -1; });

      card.hidden = !show;
      if (show) visible++;
    });

    if (counter) {
      counter.hidden = false;
      counter.textContent = visible === cards.length
        ? "Pokazano wszystkie " + cards.length + " " + plural(cards.length)
        : "Pokazano " + visible + " z " + cards.length + " " + plural(cards.length);
    }
    if (noResults) noResults.hidden = visible !== 0;
  }

  function plural(n) {
    if (n === 1) return "ogłoszenie";
    var rest = n % 10, hundreds = n % 100;
    if (rest >= 2 && rest <= 4 && (hundreds < 12 || hundreds > 14)) return "ogłoszenia";
    return "ogłoszeń";
  }

  [q, fCategory, fSource, fKind, fOpen, fNew].forEach(function (el) {
    if (!el) return;
    el.addEventListener(el.tagName === "INPUT" && el.type !== "checkbox" ? "input" : "change", apply);
  });

  apply();
})();
