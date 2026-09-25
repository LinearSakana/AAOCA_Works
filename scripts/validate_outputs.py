"""Independently validate pipeline artifacts without opening private source PDFs.

Usage: python -X utf8 scripts/validate_outputs.py PATH_TO_PIPELINE_OUTPUT
Reports contain artifact IDs and aggregate counts, never names or clinical text.
This checks referential integrity, exact section/text alignment, complete line
coverage, duplicate exclusion, chronology provenance, and cross-table counts.
It does not replace manual medical review of extraction or date semantics.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
import json
from pathlib import Path
import sys


def _truth(value):
    return value is True or str(value).lower() in {"true", "1"}


def _csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_outputs(output: Path) -> dict:
    """Return PHI-free findings; exceptions are converted to named check errors."""
    output = Path(output).resolve()
    errors, warnings = [], []

    def fail(code, identifier="", details=""):
        errors.append({"code": code, "artifact_id": identifier, "details": details})

    def local_path(value, identifier):
        if not value:
            fail("missing_artifact_reference", identifier)
            return None
        path = (output / value).resolve()
        if not path.is_relative_to(output):
            fail("artifact_reference_outside_output", identifier)
            return None
        if not path.is_file():
            fail("artifact_reference_not_found", identifier)
            return None
        return path

    tables = {}
    for name in ("patient_manifest", "document_index", "section_index", "patient_timeline", "page_index", "source_inventory"):
        try:
            tables[name] = _csv(output / f"{name}.csv")
        except (OSError, ValueError, csv.Error):
            fail("required_table_unreadable", name)
            tables[name] = []
    documents, sections, timeline = (tables[k] for k in ("document_index", "section_index", "patient_timeline"))
    manifests = tables["patient_manifest"]
    docmap, secmap = {}, {}
    for row in documents:
        identifier = row["document_id"]
        if identifier in docmap:
            fail("duplicate_document_id", identifier)
        docmap[identifier] = row
    for row in sections:
        identifier = row["section_id"]
        if identifier in secmap:
            fail("duplicate_section_id", identifier)
        secmap[identifier] = row
    canonical = [d for d in documents if not d.get("duplicate_of")]
    canonical_ids = {d["document_id"] for d in canonical}
    patient_ids = [p["patient_id"] for p in manifests]
    if len(set(patient_ids)) != len(patient_ids):
        fail("duplicate_manifest_patient_id")
    sha_groups = defaultdict(list)
    for doc in documents:
        identifier = doc["document_id"]
        for field in ("raw_text_path", "text_path", "sections_path"):
            local_path(doc.get(field, ""), identifier)
        if doc.get("patient_id") and doc["patient_id"] not in patient_ids:
            fail("document_patient_not_in_manifest", identifier)
        if doc.get("match_status", "").startswith("ambiguous") and doc.get("patient_id"):
            fail("ambiguous_document_assigned_patient", identifier)
        if doc.get("sha256"):
            sha_groups[doc["sha256"]].append(doc)
        if doc.get("duplicate_of"):
            target = docmap.get(doc["duplicate_of"])
            if not target or target.get("duplicate_of"):
                fail("duplicate_target_not_canonical", identifier)
            elif not doc.get("sha256") or target.get("sha256") != doc["sha256"]:
                fail("duplicate_target_hash_mismatch", identifier)
            elif any(doc.get(k) != target.get(k) for k in ("raw_text_path", "text_path", "sections_path")):
                fail("duplicate_artifact_reference_mismatch", identifier)
    for group in sha_groups.values():
        if sum(not d.get("duplicate_of") for d in group) != 1:
            fail("sha256_group_multiple_canonicals", group[0]["document_id"])

    section_json_by_id, coverage_actual = {}, {}
    parsed_sections, raw_pages = 0, 0
    for doc in canonical:
        identifier = doc["document_id"]
        try:
            raw = json.loads((output / doc["raw_text_path"]).read_text(encoding="utf-8"))
            normalized = json.loads((output / "normalized" / f"{identifier}.json").read_text(encoding="utf-8"))
            payload = json.loads((output / doc["sections_path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            fail("canonical_json_unreadable", identifier)
            continue
        pages = {p["page"]: p for p in normalized.get("pages", [])}
        raw_by_page = {p["page"]: p for p in raw.get("pages", [])}
        raw_pages += len(raw_by_page)
        if len(raw_by_page) != int(doc.get("page_count") or 0):
            fail("page_count_mismatch", identifier)
        if sorted(raw_by_page) != list(range(1, len(raw_by_page) + 1)):
            fail("noncontiguous_page_numbers", identifier)
        if sum(len(p.get("text", "")) for p in raw_by_page.values()) != int(doc.get("extracted_character_count") or 0):
            fail("extracted_character_count_mismatch", identifier)
        for page_number, page in pages.items():
            if page.get("text", "") != raw_by_page.get(page_number, {}).get("text", ""):
                fail("normalization_overwrote_raw_text", identifier, f"page={page_number}")
        contained = payload.get("sections", [])
        parsed_sections += len(contained)
        if int(doc.get("n_sections") or 0) != len(contained):
            fail("document_section_count_mismatch", identifier)
        counts = defaultdict(Counter)
        for ordinal, section in enumerate(contained):
            sid = section.get("section_id", "")
            section_json_by_id[sid] = section
            row = secmap.get(sid)
            if not row:
                fail("json_section_missing_from_index", sid)
                continue
            if row["text_reference"] != f"/sections/{ordinal}/text" or row["text_path"] != doc["sections_path"]:
                fail("section_text_pointer_mismatch", sid)
            for key in ("patient_id", "document_id", "section_type", "section_date", "date_source", "date_evidence", "parse_status"):
                if str(section.get(key, "")) != row.get(key, ""):
                    fail("section_index_json_mismatch", sid, f"field={key}")
            reconstructed = []
            spans = section.get("page_spans", [])
            for span in spans:
                page_number = span["page"]
                if page_number not in pages:
                    fail("section_span_page_missing", sid)
                    continue
                content = pages[page_number].get("normalized_text", "")
                chunks = content.splitlines(keepends=True) or [""]
                start, end = span["start_line"], span["end_line"]
                if start < 1 or end < start or end > len(chunks):
                    fail("section_span_line_out_of_bounds", sid)
                    continue
                if span.get("start_char") != sum(len(c) for c in chunks[:start - 1]) or span.get("end_char") != sum(len(c) for c in chunks[:end]):
                    fail("section_span_character_offset_mismatch", sid)
                reconstructed.extend(chunk.rstrip("\r\n") for chunk in chunks[start - 1:end])
                counts[page_number].update(range(start, end + 1))
            if "\n".join(reconstructed) != section.get("text", ""):
                fail("section_text_not_equal_to_normalized_spans", sid)
            if spans and (spans[0]["page"] != int(row["page_start"]) or spans[-1]["page"] != int(row["page_end"])):
                fail("section_page_boundary_mismatch", sid)
            if section.get("section_date") and not section.get("date_uncertain"):
                source, evidence = section.get("date_source", ""), section.get("date_evidence", "")
                source_base = source.removeprefix("local_ocr:")
                if source_base not in {"title_timestamp", "test_timestamp_column"} and not source_base.startswith("explicit_field:"):
                    fail("reliable_date_unsupported_provenance", sid)
                if not evidence or evidence not in section.get("text", ""):
                    fail("date_evidence_not_in_section", sid)
                if source.startswith("local_ocr:") and "date_requires_review" not in section.get("flags", []):
                    fail("ocr_date_missing_review_flag", sid)
                try:
                    date.fromisoformat(section["section_date"])
                except ValueError:
                    fail("invalid_section_date", sid)
                date_page = section.get("date_page")
                if date_page not in {s["page"] for s in spans}:
                    fail("date_page_outside_section", sid)
        for page_number, page in pages.items():
            lines = page.get("normalized_text", "").splitlines()
            nonempty = [i for i, line in enumerate(lines, 1) if line.strip()]
            uncovered = sum(counts[page_number][i] == 0 for i in nonempty)
            overlapping = sum(counts[page_number][i] > 1 for i in nonempty)
            coverage_actual[(identifier, page_number)] = (len(nonempty), uncovered, overlapping)
            if uncovered or overlapping:
                fail("section_line_coverage_failure", identifier, f"page={page_number};uncovered={uncovered};overlap={overlapping}")
    if parsed_sections != len(sections):
        fail("total_section_count_mismatch")
    for row in sections:
        if row["document_id"] not in canonical_ids:
            fail("section_uses_noncanonical_document", row["section_id"])
        local_path(row.get("text_path", ""), row["section_id"])
    if raw_pages != len(tables["page_index"]):
        fail("page_index_count_mismatch")
    try:
        coverage_rows = _csv(output / "qc" / "section_coverage.csv")
        for row in coverage_rows:
            key = (row["document_id"], int(row["page"]))
            ledger = tuple(int(row[k]) for k in ("nonempty_lines", "uncovered_lines", "overlapping_lines"))
            if coverage_actual.get(key) != ledger:
                fail("coverage_ledger_mismatch", row["document_id"])
        if len(coverage_rows) != len(coverage_actual):
            fail("coverage_ledger_count_mismatch")
    except (OSError, ValueError):
        fail("coverage_ledger_unreadable")

    event_ids, expected_dates = set(), defaultdict(list)
    for event in timeline:
        sid = event["section_id"]
        section = section_json_by_id.get(sid)
        if sid in event_ids:
            fail("duplicate_timeline_section", sid)
        event_ids.add(sid)
        if not section:
            fail("timeline_section_missing", sid)
            continue
        if event["document_id"] not in canonical_ids:
            fail("timeline_uses_duplicate_source", sid)
        if not event.get("patient_id") or event["patient_id"] != section.get("patient_id"):
            fail("timeline_patient_mismatch", sid)
        if section.get("date_uncertain") or not section.get("section_date"):
            fail("timeline_uses_uncertain_date", sid)
        if event["date"][:10] != section.get("section_date"):
            fail("timeline_date_mismatch", sid)
        if event["parse_status"] in {"failed", "empty", "text_layer_unusable", "identity_conflict"}:
            fail("timeline_uses_unusable_section", sid)
        if event.get("available_at") or not _truth(event.get("cutoff_review_required")):
            fail("timeline_cutoff_review_contract_broken", sid)
        expected_dates[event["patient_id"]].append(event["date"])
    if timeline != sorted(timeline, key=lambda r: (r["patient_id"], r["date"], r["document_id"], r["section_id"])):
        fail("timeline_not_sorted")
    for patient in manifests:
        pid = patient["patient_id"]
        docs = [d for d in documents if d.get("patient_id") == pid]
        unique = [d for d in docs if not d.get("duplicate_of")]
        statuses = Counter(d["parse_status"] for d in unique)
        expected = {"n_pdf": len(unique), "n_source_pdf": len(docs), "n_parsed_pdf": statuses["ok"],
                    "n_partial_pdf": statuses["partial"], "n_failed_pdf": statuses["failed"],
                    "n_unusable_pdf": statuses["text_layer_unusable"],
                    "n_sections": sum(s["patient_id"] == pid for s in sections)}
        if "n_empty_pdf" in patient:
            expected["n_empty_pdf"] = statuses["empty"]
        for key, count in expected.items():
            if int(patient.get(key) or 0) != count:
                fail("manifest_count_mismatch", pid, f"field={key}")
        dates = sorted(expected_dates[pid])
        if patient.get("earliest_document_date", "") != (dates[0] if dates else "") or patient.get("latest_document_date", "") != (dates[-1] if dates else ""):
            fail("manifest_date_range_mismatch", pid)
    try:
        summary = json.loads((output / "qc" / "cohort_summary.json").read_text(encoding="utf-8"))
        expected = {"cohort_patients": len(manifests), "source_pdf_files": len(documents),
                    "unique_pdf_contents": len(canonical), "exact_duplicate_copies": len(documents) - len(canonical),
                    "sections": len(sections), "timeline_events": len(timeline), "total_unique_pdf_pages": raw_pages}
        for key, value in expected.items():
            if summary.get(key) != value:
                fail("qc_summary_count_mismatch", key)
        inventory = tables["source_inventory"]
        if len(inventory) != len(documents) + 1 or sum(r.get("kind") == "cohort_csv" for r in inventory) != 1:
            fail("source_inventory_count_mismatch")
        for row in inventory:
            if row.get("kind") == "pdf":
                doc = docmap.get(row.get("document_id"))
                if not doc or doc.get("sha256") != row.get("sha256"):
                    fail("source_inventory_hash_mismatch", row.get("document_id", ""))
        if summary.get("source_hash_verification") == "passed" and any(not _truth(r.get("unchanged")) for r in inventory):
            fail("source_integrity_claim_not_supported")
        if summary.get("source_hash_verification") == "partially_unverifiable":
            count = sum(r.get("kind") == "pdf" and r.get("unchanged", "") == "" for r in inventory)
            if summary.get("source_unverifiable_count") != count:
                fail("unverifiable_source_count_mismatch")
    except (OSError, ValueError):
        fail("qc_summary_unreadable")
    return {"validation_status": "passed" if not errors else "failed", "error_count": len(errors),
            "error_types": dict(Counter(e["code"] for e in errors)), "errors": errors[:100],
            "warning_count": len(warnings), "warnings": warnings,
            "counts": {"patients": len(manifests), "source_documents": len(documents), "canonical_documents": len(canonical),
                       "pages": raw_pages, "sections": len(sections), "timeline_events": len(timeline)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, help="Optional PHI-free JSON validation report")
    args = parser.parse_args()
    result = validate_outputs(args.output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["validation_status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
