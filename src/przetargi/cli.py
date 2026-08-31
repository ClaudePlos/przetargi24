"""Wiersz poleceń portalu: `python -m przetargi <polecenie>`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .demo import demo_tenders
from .pipeline import run_update
from .render import DEFAULT_OUTPUT, SiteRenderer
from .store import DEFAULT_DATA_DIR, TenderStore, write_status

log = logging.getLogger("przetargi")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _status_path(data_dir: Path) -> Path:
    return data_dir / "status.json"


def _read_status(data_dir: Path) -> dict:
    path = _status_path(data_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Nie udało się wczytać %s: %s", path, exc)
        return {}


def cmd_update(args: argparse.Namespace) -> int:
    """Pobiera świeże ogłoszenia i zapisuje je w data/tenders.json."""
    config = load_config(args.config)
    store = TenderStore(args.data / "tenders.json").load()
    report, sources = run_update(config, store)
    store.save()

    write_status(
        _status_path(args.data),
        sources,
        report,
        [
            {"slug": c.slug, "title": c.title, "count": report.per_category.get(c.slug, 0)}
            for c in config.categories
        ],
    )

    failed = [s for s in sources if not s["ok"]]
    log.info(
        "Gotowe: +%s nowych, %s zaktualizowanych, %s scalonych, %s usuniętych, razem %s",
        report.added, report.updated, report.merged, report.removed, report.total,
    )
    _write_job_summary(report, sources)

    if failed and len(failed) == len(sources):
        log.error("Żadne źródło nie odpowiedziało poprawnie")
        return 1
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Generuje statyczną stronę z danych zapisanych w repozytorium."""
    config = load_config(args.config)
    store = TenderStore(args.data / "tenders.json").load()
    renderer = SiteRenderer(config.settings, config.categories, output=args.output)
    files = renderer.render(store, _read_status(args.data))
    log.info("Zbudowano stronę: %s plików w %s", len(files), args.output)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Aktualizacja i budowa strony w jednym kroku."""
    code = cmd_update(args)
    build_code = cmd_build(args)
    return code or build_code


def cmd_demo(args: argparse.Namespace) -> int:
    """Wypełnia bazę przykładowymi wpisami — do podglądu strony bez sieci."""
    config = load_config(args.config)
    store = TenderStore(args.data / "tenders.json")
    if not args.fresh:
        store.load()
    from .classify import classify_all

    matched = classify_all(demo_tenders(), config.categories, config.settings)
    report = store.merge(matched)
    store.touch()
    store.save()
    write_status(
        _status_path(args.data),
        [
            {
                "key": "demo", "label": "Dane przykładowe (offline)", "ok": True,
                "fetched": len(matched), "error": "", "duration_seconds": 0.0,
                "homepage": "",
            }
        ],
        report,
        [{"slug": c.slug, "title": c.title, "count": 0} for c in config.categories],
    )
    log.info("Dodano %s przykładowych ogłoszeń", report.added)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Sprawdza poprawność konfiguracji — używane w CI i przed commitem."""
    config = load_config(args.config)
    from .sources import build_sources

    sources = build_sources(config.sources)
    print(f"Kategorie ({len(config.categories)}):")
    for category in config.categories:
        print(
            f"  • {category.slug:<20} {category.name}"
            f"  [CPV: {len(category.cpv)}, słowa: {len(category.keywords)}]"
        )
    print(f"Źródła ({len(sources)}):")
    for source in sources:
        print(f"  • {source.key:<20} {source.label}")
    print("Konfiguracja jest poprawna.")
    return 0


def _write_job_summary(report, sources) -> None:
    """Dopisuje podsumowanie do panelu GitHub Actions, gdy jesteśmy w CI."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## Aktualizacja przetargów",
        "",
        f"- Nowe wpisy: **{report.added}**",
        f"- Zaktualizowane: **{report.updated}**",
        f"- Scalone duplikaty: **{report.merged}**",
        f"- Odsiane po zmianie reguł: **{report.reclassified}**",
        f"- Usunięte (przeterminowane): **{report.removed}**",
        f"- Razem w bazie: **{report.total}**",
        "",
        "| Źródło | Stan | Pobrano | Szczegóły |",
        "| --- | --- | --- | --- |",
    ]
    for source in sources:
        state = "✅ OK" if source["ok"] else "❌ błąd"
        lines.append(
            f"| {source['label']} | {state} | {source['fetched']} | {source['error'] or '—'} |"
        )
    lines += ["", "| Kategoria | Ogłoszeń |", "| --- | --- |"]
    for slug, count in sorted(report.per_category.items()):
        lines.append(f"| {slug} | {count} |")
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError as exc:
        log.warning("Nie udało się zapisać podsumowania zadania: %s", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="przetargi",
        description="Portal z polskimi przetargami publicznymi — pobieranie i generowanie strony.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="więcej komunikatów w logu")
    parser.add_argument(
        "--config", type=Path, default=None, help="katalog z konfiguracją (domyślnie ./config)"
    )
    parser.add_argument(
        "--data", type=Path, default=DEFAULT_DATA_DIR, help="katalog z danymi (domyślnie ./data)"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="katalog wyjściowy strony (domyślnie ./public)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("update", help="pobierz świeże ogłoszenia").set_defaults(func=cmd_update)
    subparsers.add_parser("build", help="zbuduj stronę z zapisanych danych").set_defaults(
        func=cmd_build
    )
    subparsers.add_parser("run", help="pobierz i zbuduj stronę").set_defaults(func=cmd_run)
    subparsers.add_parser("check", help="sprawdź konfigurację").set_defaults(func=cmd_check)
    demo = subparsers.add_parser("demo", help="wypełnij bazę przykładowymi danymi")
    demo.add_argument("--fresh", action="store_true", help="zacznij od pustej bazy")
    demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    args.data.mkdir(parents=True, exist_ok=True)
    try:
        return args.func(args)
    except ConfigError as exc:
        log.error("Błąd konfiguracji: %s", exc)
        return 2
    except KeyboardInterrupt:
        log.warning("Przerwano")
        return 130


if __name__ == "__main__":
    sys.exit(main())
