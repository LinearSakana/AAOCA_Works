"""Minimal reversible cleanup of webpage-printed PDF text.

The raw ``text`` and raw page layouts survive unchanged.  Only a conservative
allowlist of browser chrome is removed; repeated clinical titles, dates,
identifiers and measurements remain.  Every removed line is recorded locally.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

NORMALIZATION_VERSION = "web_print_minimal_v1"
# The label can be preceded by a patient name. It is removed only at a page
# margin, where it is browser print metadata rather than a clinical heading.
BROWSER_TITLE = re.compile(r"(?:360\s*视图\s*v?2\.1\s*Beta|360\s*view\s*v?2\.1\s*Beta)", re.I)
URL_LINE = re.compile(r"^(?:https?://|file:///|\(?/(?:BasicInfo|MedicalRecord|Inspection|Examination)/)", re.I)
PAGE_NUMBER = re.compile(r"^(?:第\s*\d+\s*页\s*(?:[共/]\s*\d+\s*页?)?|\d+\s*/\s*\d+)\s*$")
ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")


def normalize_text(text: str) -> str:
    """NFKC widths, horizontal spaces, and blank lines; do not reflow prose.

    NFKC can change compatibility symbols such as fullwidth digits or unit
    glyphs. Keeping raw text separately is therefore an explicit contract.
    """
    text = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = ZERO_WIDTH.sub("", text)
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def normalize_document(extracted: dict[str, Any]) -> dict[str, Any]:
    """Return a new document preserving raw text and page numbers.

    ``normalized_line_map`` maps retained normalized lines back to raw line
    numbers. Removed lines include their exact text and reason for reversibility.
    No generic frequency-based heading removal is performed.
    """
    result = copy.deepcopy(extracted)
    result["normalization_version"] = NORMALIZATION_VERSION
    removed_total = 0
    for page in result.get("pages", []):
        # A local OCR fallback is a separate representation; the original PDF
        # text and its glyph layout remain untouched in text/lines.
        source_text = page.get("analysis_text", page.get("text", ""))
        page["normalized_text_source"] = page.get("analysis_text_source", "pdf_text_layer")
        raw_lines = source_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        kept: list[tuple[str, int]] = []
        removed = []
        for index, raw in enumerate(raw_lines):
            line = normalize_text(raw)
            near_margin = index < 4 or index >= len(raw_lines) - 5
            reason = None
            if near_margin and BROWSER_TITLE.search(line):
                reason = "browser_title_at_page_margin"
            elif URL_LINE.match(line):
                reason = "browser_or_navigation_url"
            elif near_margin and PAGE_NUMBER.fullmatch(line):
                reason = "page_number_at_page_margin"
            elif line and all(unicodedata.category(char) == "Co" or char.isspace() for char in line):
                reason = "standalone_private_use_browser_icon"
            if reason:
                removed.append({"raw_line": index + 1, "text": raw, "reason": reason})
                continue
            if not line and (not kept or kept[-1][0] == ""):
                continue
            kept.append((line, index + 1))
        while kept and not kept[-1][0]:
            kept.pop()
        page["normalized_text"] = "\n".join(line for line, _ in kept)
        page["normalized_character_count"] = len(page["normalized_text"])
        page["normalized_line_map"] = [raw_line for _, raw_line in kept]
        page["removed_lines"] = removed
        removed_total += len(removed)
    result["normalized_character_count"] = sum(p["normalized_character_count"] for p in result.get("pages", []))
    result["removed_line_count"] = removed_total
    return result
