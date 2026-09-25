"""Export all sections grouped by their section_type value.

This script is intentionally standalone and is not executed by the project
automation. Run it manually with Python when the source data is available.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_SECTION_DIRS = (
    Path(r"E:\AAOCA\_Works\data\derived\v0.1\_full\sections"),
    Path(r"E:\AAOCA_Works\data\derived\v0.1_full\sections"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export sections grouped by section_type and locate their source "
            "fragments in the corresponding normalized JSON files."
        )
    )
    parser.add_argument(
        "--sections-dir",
        type=Path,
        default=None,
        help="Directory containing sections/*.json.",
    )
    parser.add_argument(
        "--normalized-dir",
        type=Path,
        default=None,
        help="Directory containing normalized/<document_id>.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for one output JSON file per section_type value.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def compact_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\x00", "")


def search_text_key(value: Any) -> str:
    """Make exact fallback matching tolerant of whitespace differences."""

    return re.sub(r"\s+", "", compact_text(value))


def find_default_sections_dir() -> Path:
    for candidate in DEFAULT_SECTION_DIRS:
        if candidate.is_dir():
            return candidate
    return DEFAULT_SECTION_DIRS[0]


def normalized_pages(normalized: Any) -> list[dict[str, Any]]:
    pages = normalized.get("pages", []) if isinstance(normalized, dict) else []
    return [page for page in pages if isinstance(page, dict)]


def fragment_from_spans(
    spans: Any, pages_by_number: dict[int, dict[str, Any]]
) -> tuple[str, list[dict[str, Any]], str | None]:
    fragments: list[str] = []
    locations: list[dict[str, Any]] = []
    errors: list[str] = []

    if not isinstance(spans, list):
        return "", [], "section has no usable page_spans"

    for span in spans:
        if not isinstance(span, dict):
            errors.append("invalid page span")
            continue

        try:
            page_number = int(span["page"])
            start = int(span["start_char"])
            end = int(span["end_char"])
        except (KeyError, TypeError, ValueError):
            errors.append("page span is missing numeric page/start_char/end_char")
            continue

        page = pages_by_number.get(page_number)
        if page is None:
            errors.append(f"normalized page {page_number} not found")
            continue

        source_text = compact_text(page.get("normalized_text", ""))
        if start < 0 or end < start or end > len(source_text):
            errors.append(
                f"invalid range page={page_number}, start={start}, end={end}, "
                f"page_length={len(source_text)}"
            )
            continue

        fragments.append(source_text[start:end])
        locations.append(
            {
                "page": page_number,
                "start_char": start,
                "end_char": end,
            }
        )

    error = "; ".join(errors) if errors else None
    return "\n".join(fragments), locations, error


def fallback_find_fragment(
    section_text: str, normalized: Any
) -> tuple[str, list[dict[str, Any]]]:
    needle = search_text_key(section_text)
    if not needle:
        return "", []

    for page in normalized_pages(normalized):
        page_text = compact_text(page.get("normalized_text", ""))
        compact_page = search_text_key(page_text)
        match_start = compact_page.find(needle)
        if match_start >= 0:
            # The compacted search cannot safely recover original offsets, so
            # return the whole page as an auditable fallback fragment.
            return page_text, [{"page": page.get("page"), "fallback": "whole_page"}]
    return "", []


def extract_sections_by_type(
    sections_dir: Path, normalized_dir: Path
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    results_by_type: dict[str, list[dict[str, Any]]] = {}
    stats = {
        "section_files": 0,
        "sections": 0,
        "matched_by_page_spans": 0,
        "matched_by_text_fallback": 0,
        "missing_normalized_files": 0,
        "errors": 0,
    }

    for section_path in sorted(sections_dir.glob("*.json")):
        stats["section_files"] += 1
        try:
            document = load_json(section_path)
        except (OSError, json.JSONDecodeError) as exc:
            stats["errors"] += 1
            print(f"WARN: cannot read {section_path}: {exc}", file=sys.stderr)
            continue

        document_id = compact_text(document.get("document_id"))
        section_entries = document.get("sections", [])
        if not document_id:
            document_id = section_path.stem
        if not isinstance(section_entries, list):
            stats["errors"] += 1
            print(f"WARN: sections is not a list: {section_path}", file=sys.stderr)
            continue

        normalized_path = normalized_dir / f"{document_id}.json"
        normalized = None
        if normalized_path.is_file():
            try:
                normalized = load_json(normalized_path)
            except (OSError, json.JSONDecodeError) as exc:
                stats["errors"] += 1
                print(f"WARN: cannot read {normalized_path}: {exc}", file=sys.stderr)
        else:
            stats["missing_normalized_files"] += 1

        pages_by_number = {
            int(page["page"]): page
            for page in normalized_pages(normalized)
            if isinstance(page.get("page"), (int, str)
            ) and str(page.get("page")).isdigit()
        }

        for section_index, section in enumerate(section_entries):
            if not isinstance(section, dict):
                continue

            section_type = compact_text(section.get("section_type")) or "missing"
            stats["sections"] += 1
            title = compact_text(section.get("section_title", section.get("title", "")))
            text = compact_text(section.get("text", ""))
            fragment = ""
            locations: list[dict[str, Any]] = []
            match_method = "not_found"
            match_error = None

            if normalized is not None:
                fragment, locations, match_error = fragment_from_spans(
                    section.get("page_spans"), pages_by_number
                )
                if fragment or locations:
                    stats["matched_by_page_spans"] += 1
                    match_method = "page_spans"
                else:
                    fragment, locations = fallback_find_fragment(text, normalized)
                    if fragment:
                        stats["matched_by_text_fallback"] += 1
                        match_method = "text_fallback_whole_page"

            item: dict[str, Any] = {
                "document_id": document_id,
                "section_index": section_index,
                "section_id": compact_text(section.get("section_id")),
                "subtype": compact_text(section.get("section_subtype")),
                "title": title,
                "text": text,
                "normalized_fragment": fragment,
                "normalized_locations": locations,
                "match_method": match_method,
            }
            if match_error:
                item["match_warning"] = match_error
            results_by_type.setdefault(section_type, []).append(item)

    return results_by_type, stats


def main() -> int:
    args = parse_args()
    sections_dir = args.sections_dir or find_default_sections_dir()
    normalized_dir = args.normalized_dir or sections_dir.parent / "normalized"
    output_dir = args.output_dir or Path(__file__).resolve().parent

    if not sections_dir.is_dir():
        print(f"ERROR: sections directory does not exist: {sections_dir}", file=sys.stderr)
        return 2
    if not normalized_dir.is_dir():
        print(f"ERROR: normalized directory does not exist: {normalized_dir}", file=sys.stderr)
        return 2

    results_by_type, stats = extract_sections_by_type(sections_dir, normalized_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for section_type, results in sorted(results_by_type.items()):
        safe_type = re.sub(r"[^0-9A-Za-z_.-]+", "_", section_type).strip("._") or "missing"
        output_path = output_dir / f"sections_{safe_type}.json"
        output = {
            "source": {
                "sections_dir": str(sections_dir),
                "normalized_dir": str(normalized_dir),
                "section_type": section_type,
            },
            "stats": {
                **stats,
                "section_type_count": len(results),
            },
            "sections": results,
        }
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(output, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"Wrote {len(results)} sections of type {section_type!r} to {output_path}")

    print(f"Detected section types: {', '.join(sorted(results_by_type)) or '(none)'}")
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
