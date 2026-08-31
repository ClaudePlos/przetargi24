"""Rejestr źródeł danych: wbudowane adaptery + źródła opisane w YAML-u."""

from __future__ import annotations

import logging
from typing import Any

from .base import FetchContext, HttpClient, Source, SourceError, SourceResult
from .generic import GenericJsonSource
from .ted import TedSource

log = logging.getLogger(__name__)

# Adaptery, które mają własną logikę zapytań i nie dają się opisać w YAML-u.
BUILTIN: dict[str, type[Source]] = {
    "ted": TedSource,
}


def build_sources(config: dict[str, Any]) -> list[Source]:
    """Buduje listę aktywnych źródeł na podstawie sekcji `sources:`."""
    entries = (config or {}).get("sources") or {}
    if not isinstance(entries, dict):
        raise SourceError("config/sources.yml: sekcja 'sources' musi być mapą")

    sources: list[Source] = []
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            log.warning("Pomijam źródło '%s': wpis nie jest mapą", key)
            continue
        if not entry.get("enabled", True):
            log.info("Źródło '%s' jest wyłączone w konfiguracji", key)
            continue

        kind = str(entry.get("type", "json")).lower()
        if kind == "builtin":
            factory = BUILTIN.get(key)
            if factory is None:
                log.error("Nieznane źródło wbudowane '%s' — pomijam", key)
                continue
            source = factory()
            if entry.get("label"):
                source.label = str(entry["label"])
            sources.append(source)
        elif kind == "json":
            try:
                sources.append(GenericJsonSource(key, entry))
            except SourceError as exc:
                log.error("Pomijam źródło '%s': %s", key, exc)
        else:
            log.error("Źródło '%s' ma nieznany typ '%s' — pomijam", key, kind)

    if not sources:
        raise SourceError("config/sources.yml: nie ma ani jednego aktywnego źródła")
    return sources


__all__ = [
    "BUILTIN",
    "FetchContext",
    "GenericJsonSource",
    "HttpClient",
    "Source",
    "SourceError",
    "SourceResult",
    "TedSource",
    "build_sources",
]
