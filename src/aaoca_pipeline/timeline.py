"""Document-level chronology, with explicit limits on future cutoff use.

An event date is not a data-availability timestamp. A note may have been written
later, or mention later outcomes. Neither this module nor a date-only filter
establishes a leakage-free prediction cohort.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .io_utils import write_csv, write_json

TIMELINE_FIELDS = [
    "patient_id", "date", "date_precision", "event_type", "document_id", "section_id",
    "source_pdf", "page", "page_end", "date_source", "date_evidence", "date_page",
    "text_path", "text_reference", "parse_status", "clinical_stage", "leakage_risk",
    "available_at", "cutoff_review_required",
    "text_source", "date_requires_review", "date_evidence_confidence", "flags", "leakage_flags", "event_subtype",
]


def make_timeline(sections: list[dict]) -> list[dict]:
    events = []
    for s in sections:
        value = s.get("section_date") or s.get("document_date")
        if not s.get("patient_id") or not value or s.get("date_uncertain"):
            continue
        if s.get("parse_status") in {"failed", "text_layer_unusable", "empty", "identity_conflict"}:
            continue
        try:
            date.fromisoformat(value[:10])
        except (ValueError, TypeError):
            continue
        events.append({
            "patient_id": s["patient_id"], "date": s.get("document_timestamp") or value,
            "date_precision": s.get("date_precision", "day"),
            "event_type": s["section_type"], "event_subtype": s.get("section_subtype", ""),
            "document_id": s["document_id"],
            "section_id": s["section_id"], "source_pdf": s["source_pdf"],
            "page": s["page_start"], "page_end": s["page_end"],
            "date_source": s.get("date_source", ""), "date_evidence": s.get("date_evidence", ""),
            "date_page": s.get("date_page", ""), "text_path": s["text_path"],
            "text_reference": s["text_reference"], "parse_status": s["parse_status"],
            "clinical_stage": s.get("clinical_stage", "unknown"),
            "leakage_risk": s.get("leakage_risk", "unreviewed"), "available_at": "",
            "cutoff_review_required": True,
            "text_source": s.get("text_source", "pdf_text_layer"),
            "date_requires_review": s.get("date_requires_review", False),
            "date_evidence_confidence": s.get("date_evidence_confidence"),
            "flags": s.get("flags", []), "leakage_flags": s.get("leakage_flags", []),
        })
    return sorted(events, key=lambda r: (r["patient_id"], r["date"], r["document_id"], r["section_id"]))


def export_before_cutoff(output: Path, cutoff: str, patient_id: str | None = None) -> dict:
    """Strict date-only subset; same-day, unknown dates, and uncertain dates excluded."""
    from datetime import datetime
    import json
    cutoff_date = date.fromisoformat(cutoff)
    meta = json.loads((output / "run_metadata.json").read_text(encoding="utf-8"))
    if meta.get("status") != "complete":
        raise ValueError("Cutoff export requires a complete pipeline run")
    with (output / "patient_timeline.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = [r for r in rows if (not patient_id or r["patient_id"] == patient_id)
                and date.fromisoformat(r["date"][:10]) < cutoff_date
                and r.get("date_requires_review", "False").lower() not in {"true", "1"}]
    # The output filename never interpolates a user-controlled patient ID.
    target = output / "cutoffs" / f"before_{cutoff_date.isoformat()}.csv"
    write_csv(target, selected, TIMELINE_FIELDS)
    receipt = {
        "cutoff": cutoff_date.isoformat(), "relation": "strictly_before_day",
        "patient_id_filter": patient_id or "", "n_events": len(selected),
        "path": str(target), "created_at": datetime.now().astimezone().isoformat(),
        "leakage_free": False,
        "unreviewed_ocr_dates_excluded": True,
        "limitation": "Event date only; available_at unknown. Retrospective notes and outcomes need clinical review.",
    }
    write_json(target.with_suffix(".json"), receipt)
    return receipt
