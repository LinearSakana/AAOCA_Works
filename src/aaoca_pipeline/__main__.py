"""CLI entry point. Paths in a JSON config resolve relative to that config."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _resolve_config_path(value: str | Path, config_dir: Path) -> str:
    """Resolve relative config paths and expand cross-platform env variables."""
    expanded = os.path.expanduser(os.path.expandvars(str(value)))
    path = Path(expanded)
    if not path.is_absolute():
        path = config_dir / path
    return str(path.resolve())


def main() -> None:
    parser = argparse.ArgumentParser(description="AAOCA local PDF preprocessing v0.1")
    parser.add_argument("--config", type=Path, help="JSON configuration file")
    parser.add_argument("--csv", type=Path, help="Override cohort CSV")
    parser.add_argument("--pdf-root", action="append", type=Path, help="Read-only PDF root; repeatable")
    parser.add_argument("--output", type=Path, help="Derived output directory")
    parser.add_argument("--cache", type=Path, help="Versioned local extraction cache")
    parser.add_argument("--refresh-cache", action="store_true", help="Re-extract PDF text layers")
    parser.add_argument("--ocr", choices=["off", "missing"], help="Local OCR only for flagged pages; default off")
    parser.add_argument("--ocr-model-dir", type=Path, help="Directory of predownloaded local RapidOCR models")
    parser.add_argument("--ocr-max-pages", type=int, help="Maximum OCR pages per PDF; 0 means all eligible pages")
    parser.add_argument("--ocr-workers", type=int, help="Local OCR worker processes; default 4")
    parser.add_argument("--scope", help="Human-readable input-scope label")
    parser.add_argument("--before", help="Export reliable sections strictly before YYYY-MM-DD (date-only)")
    parser.add_argument("--patient-id", help="Optional patient filter for cutoff export only")
    args = parser.parse_args()
    settings = {}
    if args.config:
        config_path = args.config.resolve()
        settings = json.loads(config_path.read_text(encoding="utf-8-sig"))
        for key in ["cohort_csv", "output_root", "cache_root", "ocr_model_dir"]:
            if key in settings:
                settings[key] = _resolve_config_path(settings[key], config_path.parent)
        settings["pdf_roots"] = [
            _resolve_config_path(path, config_path.parent)
            for path in settings.get("pdf_roots", [])
        ]
    for key, value in [("cohort_csv", args.csv), ("output_root", args.output), ("cache_root", args.cache)]:
        if value:
            settings[key] = str(value.resolve())
    if args.pdf_root:
        settings["pdf_roots"] = [str(p.resolve()) for p in args.pdf_root]
    if args.scope:
        settings["scope"] = args.scope
    if args.ocr is not None:
        settings["ocr"] = args.ocr
    if args.ocr_model_dir is not None:
        settings["ocr_model_dir"] = str(args.ocr_model_dir.resolve())
    if args.ocr_max_pages is not None:
        if args.ocr_max_pages < 0:
            parser.error("--ocr-max-pages cannot be negative")
        settings["ocr_max_pages"] = args.ocr_max_pages
    if args.ocr_workers is not None:
        settings["ocr_workers"] = args.ocr_workers
    if args.before:
        if "output_root" not in settings:
            parser.error("--before requires --output or a configured output_root")
        from .timeline import export_before_cutoff
        result = export_before_cutoff(Path(settings["output_root"]), args.before, args.patient_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not all(settings.get(k) for k in ["cohort_csv", "pdf_roots", "output_root"]):
        parser.error("Provide --config, or --csv, --pdf-root and --output")
    settings["refresh_cache"] = args.refresh_cache
    from .pipeline import run_pipeline
    result = run_pipeline(settings)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
