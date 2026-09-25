"""QC rows are evidence for review, never automatic cohort exclusion."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .io_utils import write_csv, write_json


def build_qc(output: Path, patients: list[dict], documents: list[dict], sections: list[dict],
             matching_issues: list[dict], pages: list[dict], timeline: list[dict]) -> dict:
    qc = output / "qc"
    canonical = [d for d in documents if not d.get("duplicate_of")]
    write_csv(qc / "matching_issues.csv", matching_issues,
              ["issue_type", "severity", "patient_id", "document_id", "field", "csv_row", "csv_rows", "duplicate_of", "details", "detail"])
    write_csv(qc / "unmatched_files.csv", [d for d in documents if not d.get("patient_id")],
              ["document_id", "source_pdf", "match_status", "match_method", "candidate_patient_ids", "sha256", "duplicate_of"])
    write_csv(qc / "patients_without_pdf.csv", [p for p in patients if p["n_pdf"] == 0],
              ["patient_id", "has_inpatient_id", "has_outpatient_id", "parse_status"])
    write_csv(qc / "parse_failures.csv", [d for d in canonical if d["parse_status"] != "ok"],
              ["document_id", "patient_id", "source_pdf", "page_count", "extracted_character_count", "parse_status", "flags"])
    write_csv(qc / "empty_or_tiny_text.csv", [p for p in pages if p.get("char_count", 0) < 80],
              ["document_id", "patient_id", "source_pdf", "page", "char_count", "normalized_character_count", "extraction_status", "flags"])
    write_csv(qc / "page_issues.csv", [p for p in pages if p.get("flags") or p.get("extraction_status") not in {"ok", "success"}],
              ["document_id", "patient_id", "source_pdf", "page", "char_count", "normalized_character_count", "extraction_status", "flags"])
    write_csv(qc / "uncertain_documents.csv", [s for s in sections if s["section_type"] != "nonclinical"
              and (s["section_type"] == "unknown" or not s["section_date"]
                   or s.get("date_uncertain") or s["parse_status"] != "ok")],
              ["document_id", "patient_id", "section_id", "source_pdf", "page_start", "page_end", "section_type",
               "section_date", "date_source", "date_uncertain", "parse_status", "flags", "text_path", "text_reference", "section_subtype"])
    groups = defaultdict(list)
    for doc in documents:
        groups[doc["sha256"] or doc["document_id"]].append(doc)
    duplicates = []
    for sha, group in groups.items():
        if len(group) > 1:
            for d in group:
                duplicates.append({"duplicate_group": sha, "duplicate_kind": "exact_file_sha256",
                                   "document_id": d["document_id"], "patient_id": d["patient_id"],
                                   "source_pdf": d["source_pdf"], "canonical_document_id": d.get("duplicate_of") or d["document_id"]})
    write_csv(qc / "duplicate_candidates.csv", duplicates,
              ["duplicate_group", "duplicate_kind", "document_id", "patient_id", "source_pdf", "canonical_document_id"])
    write_csv(qc / "dates_requiring_review.csv", [s for s in sections if s["section_type"] != "nonclinical"
              and (s.get("date_requires_review") or s.get("date_uncertain"))],
              ["patient_id", "document_id", "section_id", "section_date", "date_source", "date_evidence", "date_page",
               "date_line", "date_evidence_confidence", "date_uncertain", "flags", "text_path", "text_reference"])
    summary = {
        "cohort_patients": len(patients), "source_pdf_files": len(documents),
        "unique_pdf_contents": len(canonical), "exact_duplicate_copies": len(documents) - len(canonical),
        "patients_with_pdf": sum(p["n_pdf"] > 0 for p in patients),
        "patients_without_pdf": sum(p["n_pdf"] == 0 for p in patients),
        "matched_unique_pdfs": sum(bool(d.get("patient_id")) for d in canonical),
        "unmatched_unique_pdfs": sum(not d.get("patient_id") for d in canonical),
        "total_unique_pdf_pages": sum(d["page_count"] for d in canonical),
        "total_extracted_characters": sum(d["extracted_character_count"] for d in canonical),
        "pdf_parse_status": dict(Counter(d["parse_status"] for d in canonical)),
        "pdf_flags": dict(Counter(f for d in canonical for f in d.get("flags", []))),
        "page_status": dict(Counter(p["extraction_status"] for p in pages)),
        "page_flags": dict(Counter(f for p in pages for f in p.get("flags", []))),
        "sections": len(sections), "section_types": dict(Counter(s["section_type"] for s in sections)),
        "sections_with_date": sum(bool(s["section_date"]) and not s.get("date_uncertain") for s in sections),
        "sections_without_date": sum(not s["section_date"] or bool(s.get("date_uncertain")) for s in sections),
        "timeline_events": len(timeline), "patients_with_timeline": len({r["patient_id"] for r in timeline}),
        "matching_issue_types": dict(Counter(i.get("issue_type", "unknown") for i in matching_issues)),
        "empty_pages": sum(p.get("char_count", 0) == 0 for p in pages),
        "tiny_nonempty_pages": sum(0 < p.get("char_count", 0) < 80 for p in pages),
    }
    write_json(qc / "cohort_summary.json", summary)
    write_csv(qc / "cohort_summary.csv", [{"metric": k, "value": v} for k, v in summary.items()], ["metric", "value"])
    return summary
