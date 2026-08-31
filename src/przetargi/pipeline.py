"""Przebieg aktualizacji: pobranie ze źródeł, klasyfikacja, zapis."""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

from .classify import classify, classify_all
from .config import Config
from .models import Tender, today
from .sources import FetchContext, HttpClient, Source, SourceError, SourceResult, build_sources
from .store import TenderStore, UpdateReport

log = logging.getLogger(__name__)


def fetch_source(source: Source, ctx: FetchContext) -> tuple[list[Tender], SourceResult]:
    """Odpytuje jedno źródło. Błąd nie przerywa przebiegu — zostaje w raporcie."""
    started = time.monotonic()
    tenders: list[Tender] = []
    try:
        for tender in source.fetch(ctx):
            tenders.append(tender)
        result = SourceResult(
            key=source.key,
            label=source.label,
            ok=True,
            fetched=len(tenders),
            duration_seconds=time.monotonic() - started,
        )
        log.info("Źródło %s: pobrano %s ogłoszeń", source.key, len(tenders))
    except (SourceError, ValueError, KeyError, TypeError) as exc:
        # Zwracamy to, co zdążyliśmy pobrać przed błędem — częściowy wynik
        # jest lepszy niż pusty dzień w portalu.
        result = SourceResult(
            key=source.key,
            label=source.label,
            ok=False,
            fetched=len(tenders),
            error=f"{type(exc).__name__}: {exc}"[:400],
            duration_seconds=time.monotonic() - started,
        )
        log.error("Źródło %s zawiodło: %s", source.key, exc)
    return tenders, result


def reclassify_store(config: Config, store: TenderStore) -> int:
    """Przelicza kategorie dla całej bazy i usuwa wpisy, które już nie pasują.

    Bez tego zmiana reguł w `config/categories/` działałaby tylko na świeżo
    pobrane ogłoszenia, a wpisy zapisane pod starymi regułami zostawałyby
    w portalu z nieaktualną kategorią — także wtedy, gdy nowe reguły uznają
    je za pomyłkę.
    """
    odsiane = []
    for tender_id, tender in list(store.tenders.items()):
        classify(tender, config.categories, config.settings)
        if not tender.categories:
            odsiane.append(tender_id)
    for tender_id in odsiane:
        del store.tenders[tender_id]
    if odsiane:
        log.info("Po zmianie reguł odsiano %s wpisów, które przestały pasować", len(odsiane))
    return len(odsiane)


def run_update(
    config: Config,
    store: TenderStore,
    reference: dt.date | None = None,
) -> tuple[UpdateReport, list[dict[str, Any]]]:
    """Pełny przebieg: pobranie, dopasowanie kategorii, scalenie, czyszczenie."""
    reference = reference or today()
    settings = config.settings
    date_from = reference - dt.timedelta(days=max(0, settings.lookback_days))

    http = HttpClient(timeout=settings.timeout, retries=settings.retries)
    ctx = FetchContext(
        settings=settings,
        date_from=date_from,
        date_to=reference,
        http=http,
        limit=settings.max_per_source,
        time_budget=settings.time_budget,
    )

    log.info("Pobieram ogłoszenia z zakresu %s – %s", date_from, reference)
    harvested: list[Tender] = []
    results: list[dict[str, Any]] = []
    try:
        for source in build_sources(config.sources):
            ctx.zacznij_odliczanie()
            tenders, result = fetch_source(source, ctx)
            harvested.extend(tenders)
            entry = result.to_dict()
            entry["homepage"] = getattr(source, "homepage", "")
            results.append(entry)
    finally:
        http.close()

    matched = classify_all(harvested, config.categories, settings)
    log.info(
        "Do kategorii pasuje %s z %s pobranych ogłoszeń", len(matched), len(harvested)
    )

    report = store.merge(matched, reference)
    report.reclassified = reclassify_store(config, store)
    report.removed = store.prune(settings.retention_days, reference)
    report.total = len(store.tenders)
    report.per_category = {
        category.slug: len(store.by_category(category.slug)) for category in config.categories
    }
    store.touch()
    return report, results
