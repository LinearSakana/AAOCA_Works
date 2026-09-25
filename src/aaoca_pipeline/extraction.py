"""Read PDF text layers locally, retaining page boundaries and quality evidence.

Nonempty output is NOT equivalent to a usable clinical text layer.  A substantial
part of this cohort's macOS exports stores Chinese glyphs as vector paths while
leaving Latin letters and numbers as text.  We diagnose that condition from paint
operations and preserve the incomplete output without calling it successful.

No OCR, network access, or source-file writes happen in this module.  A later
local OCR adapter may consume ``ocr_recommended`` pages explicitly.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

import fitz

LOGGER = logging.getLogger(__name__)
EXTRACTOR_VERSION = "pymupdf_full_page_v1"
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]")


def _quality(text: str, diagnostics: dict[str, Any]) -> tuple[str, list[str]]:
    """Conservative, inspectable rules calibrated against actual cohort pages.

    Low CJK *ratio* is deliberately not a failure: numeric laboratory tables
    contain few Chinese characters.  Small filled paths are only evidence of
    outlined text when many occur and the corresponding Chinese text is absent.
    """
    count = len(text.strip())
    cjk = len(CJK_RE.findall(text))
    glyphs = diagnostics.get("character_sized_vector_paths", 0)
    paints = diagnostics.get("paint_operation_count", 0)
    image_area = diagnostics.get("largest_image_page_fraction", 0)
    flags: list[str] = []
    if not count:
        flags.append("empty_text")
        if paints == 0:
            return "empty", flags + ["blank_page"]
        flags.append("text_layer_missing")
    elif count < 40:
        flags.append("suspiciously_tiny_text")
    if not cjk and count:
        flags.append("no_cjk_text")
    if glyphs >= 20 and cjk < 5:
        flags.append("vector_outlined_text_suspected")
    elif glyphs >= 100 and glyphs > cjk * 2:
        flags.append("mixed_vector_and_text_content_suspected")
    if image_area >= 0.25 and (cjk < 5 or count < 80):
        flags.append("image_based_content_suspected")
    replacements = text.count("\ufffd")
    if replacements >= 3 and replacements / max(count, 1) >= 0.02:
        flags.append("possible_encoding_issue")
    if diagnostics.get("off_page_character_count", 0):
        flags.append("off_page_text")
    if "vector_outlined_text_suspected" in flags:
        return "text_layer_unusable", flags
    if not count:
        return "text_layer_unusable", flags
    if any(flag in flags for flag in (
        "mixed_vector_and_text_content_suspected", "image_based_content_suspected",
        "possible_encoding_issue", "suspiciously_tiny_text",
    )):
        return "partial", flags
    return "ok", flags


def _page_diagnostics(page: fitz.Page, lines: list[dict[str, Any]]) -> dict[str, Any]:
    # bboxlog is much smaller and faster than decoding all vector control points.
    paint_log = page.get_bboxlog()
    operation_counts = Counter(operation for operation, *_ in paint_log)
    bounds = page.rect
    area = max(bounds.width * bounds.height, 1)
    image_fractions = []
    vector_glyphs = 0
    for operation, bbox, *_ in paint_log:
        rect = fitz.Rect(bbox)
        if operation == "fill-path" and 2 < rect.width < 22 and 2 < rect.height < 22:
            vector_glyphs += 1
        if operation == "fill-image":
            intersection = rect & bounds
            image_fractions.append(max(intersection.width, 0) * max(intersection.height, 0) / area)
    # Text may exist beyond the physical page after a hospital webpage was
    # printed. Preserve it, but expose that it would not be fully visible.
    off_page_count = sum(
        len(span["text"])
        for line in lines for span in line.get("spans", [])
        if not bounds.contains(fitz.Rect(span["bbox"]))
    )
    return {
        "width": round(bounds.width, 3), "height": round(bounds.height, 3),
        "paint_operation_count": len(paint_log),
        "paint_operations": dict(operation_counts),
        "character_sized_vector_paths": vector_glyphs,
        "largest_image_page_fraction": round(max(image_fractions, default=0), 4),
        # This counts characters in spans crossing the boundary. It is an upper
        # bound, not the exact number of invisible glyphs.
        "off_page_character_count": off_page_count,
        "off_page_count_method": "characters_in_spans_crossing_page_boundary",
    }


def _extract_page(page: fitz.Page) -> dict[str, Any]:
    flags = fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_MEDIABOX_CLIP
    clip = fitz.INFINITE_RECT()
    text = page.get_text("text", flags=flags, clip=clip, sort=False)
    layout = page.get_text("dict", flags=flags, clip=clip, sort=False)
    lines = []
    for block in layout.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [{"text": s["text"], "bbox": list(s["bbox"])} for s in line["spans"]]
            lines.append({
                "line": len(lines) + 1,
                "text": "".join(span["text"] for span in spans),
                "bbox": list(line["bbox"]), "spans": spans,
            })
    diagnostics = _page_diagnostics(page, lines)
    status, quality_flags = _quality(text, diagnostics)
    return {
        "page": page.number + 1, "text": text, "char_count": len(text),
        "cjk_character_count": len(CJK_RE.findall(text)),
        "extraction_status": status, "flags": quality_flags,
        "extractor": EXTRACTOR_VERSION,
        "ocr_recommended": status == "text_layer_unusable" or any(f in quality_flags for f in (
            "mixed_vector_and_text_content_suspected", "image_based_content_suspected", "possible_encoding_issue",
        )),
        "diagnostics": diagnostics, "lines": lines,
    }


def _fallback_page(path: Path, page_number: int) -> dict[str, Any]:
    """Independent text-layer fallback, used only after a primary page error.

    Changing parsers cannot recover text that was converted to vector outlines;
    such pages are therefore not repeatedly parsed by every library.
    """
    from pypdf import PdfReader

    text = PdfReader(path).pages[page_number - 1].extract_text() or ""
    return {
        "page": page_number, "text": text, "char_count": len(text),
        "cjk_character_count": len(CJK_RE.findall(text)),
        "extraction_status": "partial" if text.strip() else "failed",
        "extractor": "pypdf_exception_fallback",
        "flags": ["primary_extractor_failed", "fallback_quality_unverified"],
        "ocr_recommended": not text.strip(), "diagnostics": {}, "lines": [],
    }


def extract_pdf(path: Path) -> dict[str, Any]:
    """Return JSON-serializable page text, diagnostics, and document status.

    Error messages are intentionally reduced to exception types: parser errors
    can contain source paths, patient identifiers, or snippets of source data.
    ``ok`` means the extraction quality checks passed, not that clinical facts
    or reading order have been independently validated.
    """
    path = Path(path)
    result: dict[str, Any] = {
        "page_count": 0, "extracted_character_count": 0,
        "parse_status": "failed", "extractor": EXTRACTOR_VERSION,
        "flags": [], "pages": [], "extraction_success": False,
        "obvious_empty_output": True, "ocr_recommended_page_count": 0,
    }
    try:
        with fitz.open(path) as document:
            if document.needs_pass:
                result["flags"] = ["encrypted_pdf"]
                return result
            result["page_count"] = len(document)
            for page_index in range(len(document)):
                try:
                    page_result = _extract_page(document[page_index])
                except Exception as error:
                    LOGGER.warning("PDF page extraction failed: page=%d type=%s", page_index + 1, type(error).__name__)
                    try:
                        page_result = _fallback_page(path, page_index + 1)
                    except Exception as fallback_error:
                        page_result = {
                            "page": page_index + 1, "text": "", "char_count": 0,
                            "cjk_character_count": 0, "extraction_status": "failed",
                            "extractor": EXTRACTOR_VERSION, "ocr_recommended": True,
                            "flags": ["page_extraction_failed"], "diagnostics": {}, "lines": [],
                            "error_type": type(fallback_error).__name__,
                        }
                result["pages"].append(page_result)
    except Exception as error:
        result["flags"] = ["pdf_open_failed"]
        result["error_type"] = type(error).__name__
        LOGGER.warning("PDF open failed: type=%s", type(error).__name__)
        return result

    pages = result["pages"]
    result["extracted_character_count"] = sum(page["char_count"] for page in pages)
    result["cjk_character_count"] = sum(page["cjk_character_count"] for page in pages)
    result["obvious_empty_output"] = not any(page["text"].strip() for page in pages)
    result["ocr_recommended_page_count"] = sum(page["ocr_recommended"] for page in pages)
    result["page_status_counts"] = dict(Counter(page["extraction_status"] for page in pages))
    result["flags"] = sorted({flag for page in pages for flag in page["flags"]})
    active = [page for page in pages if "blank_page" not in page["flags"]]
    if not active:
        result["parse_status"] = "empty"
    elif all(page["extraction_status"] == "failed" for page in active):
        result["parse_status"] = "failed"
    elif result["cjk_character_count"] == 0 and any(
        page["extraction_status"] == "text_layer_unusable" for page in active
    ):
        result["parse_status"] = "text_layer_unusable"
    elif all(page["extraction_status"] == "ok" for page in active):
        result["parse_status"] = "ok"
    else:
        result["parse_status"] = "partial"
    result["extraction_success"] = result["parse_status"] == "ok"
    return result
