"""Wczytywanie konfiguracji portalu i definicji kategorii z plików YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .text import collapse_whitespace

def _repo_root() -> Path:
    """Katalog projektu — działa przy uruchomieniu z repozytorium i po instalacji.

    Przy `pip install -e .` pakiet leży w ./src, więc katalog wyżej to repozytorium.
    Po zwykłej instalacji pakiet trafia do site-packages i wtedy konfiguracji
    szukamy w bieżącym katalogu roboczym (albo tam, gdzie wskaże `--config`).
    """
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "config" / "categories").is_dir():
        return candidate
    return Path.cwd()


REPO_ROOT = _repo_root()
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"


class ConfigError(RuntimeError):
    """Konfiguracja jest niepoprawna — przerywamy zamiast milczeć."""


@dataclass
class Category:
    slug: str
    name: str
    description: str = ""
    emoji: str = ""
    order: int = 100
    enabled: bool = True
    cpv: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    min_score: int | None = None

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}".strip()


@dataclass
class Settings:
    site: dict[str, Any] = field(default_factory=dict)
    fetch: dict[str, Any] = field(default_factory=dict)
    store: dict[str, Any] = field(default_factory=dict)
    classify: dict[str, Any] = field(default_factory=dict)

    @property
    def site_url(self) -> str:
        # Zmienna środowiskowa wygrywa — w Actions ustawia ją krok deploy Pages.
        url = os.environ.get("SITE_URL") or self.site.get("url") or ""
        return url.rstrip("/")

    @property
    def lookback_days(self) -> int:
        # Ręczne uruchomienie workflow może poszerzyć zakres bez edycji pliku.
        override = os.environ.get("PRZETARGI_LOOKBACK_DAYS", "").strip()
        if override.isdigit() and int(override) > 0:
            return int(override)
        return int(self.fetch.get("lookback_days", 7))

    @property
    def max_per_source(self) -> int:
        return int(self.fetch.get("max_per_source", 600))

    @property
    def max_pages(self) -> int:
        return int(self.fetch.get("max_pages", 12))

    @property
    def timeout(self) -> int:
        return int(self.fetch.get("timeout_seconds", 60))

    @property
    def retries(self) -> int:
        return int(self.fetch.get("retries", 3))

    @property
    def retention_days(self) -> int:
        return int(self.store.get("retention_days", 120))


@dataclass
class Config:
    settings: Settings
    categories: list[Category]
    sources: dict[str, Any] = field(default_factory=dict)

    def category(self, slug: str) -> Category | None:
        return next((c for c in self.categories if c.slug == slug), None)


def _as_list(value: Any, field_name: str, source: Path) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ConfigError(f"{source}: pole '{field_name}' musi być listą, a jest {type(value).__name__}")


def load_category(path: Path) -> Category:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: nie udało się sparsować YAML — {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: plik kategorii musi zawierać mapę pól")

    slug = str(raw.get("slug") or path.stem).strip()
    if not slug:
        raise ConfigError(f"{path}: brak wymaganego pola 'slug'")

    match = raw.get("match") or {}
    if not isinstance(match, dict):
        raise ConfigError(f"{path}: sekcja 'match' musi być mapą")

    cpv = _as_list(match.get("cpv"), "match.cpv", path)
    keywords = _as_list(match.get("keywords"), "match.keywords", path)
    if not cpv and not keywords:
        raise ConfigError(
            f"{path}: kategoria musi mieć wypełnione 'match.cpv' albo 'match.keywords'"
        )

    min_score = match.get("min_score", raw.get("min_score"))
    return Category(
        slug=slug,
        name=collapse_whitespace(str(raw.get("name") or slug)),
        description=collapse_whitespace(str(raw.get("description") or "")),
        emoji=str(raw.get("emoji") or "").strip(),
        order=int(raw.get("order", 100)),
        enabled=bool(raw.get("enabled", True)),
        cpv=cpv,
        keywords=keywords,
        exclude_keywords=_as_list(match.get("exclude_keywords"), "match.exclude_keywords", path),
        min_score=int(min_score) if min_score is not None else None,
    )


def load_categories(config_dir: Path | None = None) -> list[Category]:
    """Wczytuje config/categories/*.yml, pomijając pliki zaczynające się od '_'."""
    directory = (config_dir or DEFAULT_CONFIG_DIR) / "categories"
    if not directory.is_dir():
        raise ConfigError(f"Brak katalogu z kategoriami: {directory}")

    categories: list[Category] = []
    seen: dict[str, Path] = {}
    for path in sorted(list(directory.glob("*.yml")) + list(directory.glob("*.yaml"))):
        if path.name.startswith("_"):
            continue
        category = load_category(path)
        if category.slug in seen:
            raise ConfigError(
                f"{path}: slug '{category.slug}' jest już użyty w {seen[category.slug]}"
            )
        seen[category.slug] = path
        if category.enabled:
            categories.append(category)

    if not categories:
        raise ConfigError(f"{directory}: nie znaleziono żadnej włączonej kategorii")
    categories.sort(key=lambda c: (c.order, c.name))
    return categories


def load_settings(config_dir: Path | None = None) -> Settings:
    path = (config_dir or DEFAULT_CONFIG_DIR) / "settings.yml"
    raw: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path}: nie udało się sparsować YAML — {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: plik ustawień musi zawierać mapę pól")
    return Settings(
        site=raw.get("site") or {},
        fetch=raw.get("fetch") or {},
        store=raw.get("store") or {},
        classify=raw.get("classify") or {},
    )


def load_sources_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Wczytuje config/sources.yml — definicje źródeł danych."""
    path = (config_dir or DEFAULT_CONFIG_DIR) / "sources.yml"
    if not path.is_file():
        raise ConfigError(f"Brak pliku ze źródłami: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: nie udało się sparsować YAML — {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
        raise ConfigError(f"{path}: oczekiwano sekcji 'sources' z mapą źródeł")
    return raw


def load_config(config_dir: Path | None = None) -> Config:
    return Config(
        settings=load_settings(config_dir),
        categories=load_categories(config_dir),
        sources=load_sources_config(config_dir),
    )
