"""Execute the full local pipeline with immutable-source verification.

Every discovered source gets a document-index row. Exact byte duplicates are
retained there, but a single canonical copy contributes sections and timeline
events. Cache files contain only extraction results, not patient assignments;
matching and all downstream rules are rerun every time.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import time
import uuid

from . import __version__
from .io_utils import relative_output, sha256_file, validate_output_locations, write_csv, write_json, write_text
from .quality_control import build_qc
from .timeline import make_timeline, TIMELINE_FIELDS

DOCUMENT_FIELDS = [
    "patient_id", "document_id", "source_pdf", "relative_source", "source_root", "sha256",
    "file_size", "mtime_ns", "match_status", "match_method", "candidate_patient_ids", "duplicate_of",
    "page_count", "page_start", "page_end", "extracted_character_count", "normalized_character_count",
    "document_type", "document_date", "date_status", "earliest_section_date", "latest_section_date",
    "n_sections", "parse_status", "raw_parse_status", "extractor", "flags", "raw_text_path", "text_path", "sections_path",
    "ocr_attempted_page_count", "ocr_recovered_page_count", "ocr_character_count", "header_crosschecked", "identifier_conflict",
]
SECTION_FIELDS = [
    "patient_id", "document_id", "section_id", "source_pdf", "page_start", "page_end", "line_start", "line_end",
    "section_type", "section_title", "section_date", "document_date", "document_timestamp", "date_source",
    "date_precision", "date_evidence", "date_page", "date_uncertain", "parse_status", "flags", "page_spans",
    "clinical_stage", "leakage_risk", "available_at", "cutoff_review_required", "text_path", "text_reference",
    "text_source", "date_requires_review", "date_evidence_confidence", "date_line", "leakage_flags", "section_subtype",
]


def _logger(output: Path) -> logging.Logger:
    logger = logging.getLogger("aaoca_pipeline")
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    (output / "logs").mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in [logging.FileHandler(output / "logs" / "pipeline.log", encoding="utf-8"), logging.StreamHandler()]:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def _cache_fingerprint() -> str:
    from . import extraction
    content = Path(extraction.__file__).read_bytes()
    versions = [(p, importlib.metadata.version(p)) for p in ["PyMuPDF", "pypdf"]]
    return hashlib.sha256(content + repr(versions).encode()).hexdigest()[:16]


def _extract_cached(path: Path, sha: str, cache: Path, fingerprint: str, refresh: bool) -> tuple[dict, bool]:
    from .extraction import extract_pdf
    target = cache / fingerprint / f"{sha}.json"
    if target.exists() and not refresh:
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if data.get("cache_sha256") == sha and data.get("cache_fingerprint") == fingerprint:
                return data, True
        except (OSError, ValueError):
            pass  # An interrupted/invalid cache file is recomputed, not trusted.
    data = extract_pdf(path)
    data["cache_sha256"] = sha
    data["cache_fingerprint"] = fingerprint
    # Do not cache patient IDs or source-path-derived assignments.
    write_json(target, data)
    return data, False


def run_pipeline(settings: dict) -> dict:
    """Ensure errors have a run receipt and file log handles always close."""
    settings = {**settings, "run_id": uuid.uuid4().hex}
    try:
        return _run_pipeline(settings)
    except Exception as error:
        receipt_path = Path(settings["output_root"]) / "run_metadata.json"
        if receipt_path.is_file():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt.get("run_id") == settings["run_id"]:
                    receipt.update(status="failed", error_type=type(error).__name__,
                                   finished_at=datetime.now().astimezone().isoformat())
                    write_json(receipt_path, receipt)
            except (ValueError, OSError):
                pass
        raise
    finally:
        logger = logging.getLogger("aaoca_pipeline")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)


def _run_pipeline(settings: dict) -> dict:
    from .matching import load_cohort, scan_and_match, finalize_match
    from .normalization import normalize_document
    from .structure import segment_document

    started = time.perf_counter()
    csv_path = Path(settings["cohort_csv"]).resolve()
    roots = list(dict.fromkeys(Path(p).resolve() for p in settings["pdf_roots"]))
    output = Path(settings["output_root"]).resolve()
    cache = Path(settings.get("cache_root", output / "cache")).resolve()
    if not csv_path.is_file() or not all(p.is_dir() for p in roots):
        raise ValueError("Cohort CSV and every configured PDF root must exist")
    validate_output_locations([output, cache], roots, csv_path)
    logger = _logger(output)
    metadata = {
        "pipeline_version": __version__, "started_at": datetime.now().astimezone().isoformat(),
        "run_id": settings["run_id"],
        "code_sha256": {p.name: sha256_file(p) for p in Path(__file__).parent.glob("*.py")},
        "status": "running", "settings": settings, "network_processing": False,
        "raw_inputs_are_read_only": True, "ocr": settings.get("ocr", "off"),
        "python_packages": {p: importlib.metadata.version(p) for p in ["PyMuPDF", "pypdf"]},
    }
    write_json(output / "run_metadata.json", metadata)
    csv_sha = sha256_file(csv_path)
    cohort = load_cohort(csv_path, settings.get("columns"))
    patients = cohort["patients"]
    scanned = scan_and_match(roots, patients)
    files = scanned["files"]
    for record in files:
        # Unreadable sources have no content hash. They must never collapse
        # into a single empty-SHA group or share an extraction cache entry.
        record["content_key"] = record["sha256"] or "unreadable_" + record["document_id"]
    issues = cohort.get("issues", []) + scanned.get("issues", [])
    logger.info("Cohort=%s source PDFs=%s roots=%s", len(patients), len(files), len(roots))
    extracted_by_sha = {}
    fingerprint = _cache_fingerprint()
    cache_hits = 0
    for idx, file_record in enumerate(files):
        sha = file_record["content_key"]
        if sha not in extracted_by_sha:
            if file_record.get("scan_status") == "failed":
                extracted, hit = {"page_count": 0, "extracted_character_count": 0, "parse_status": "failed",
                                  "pages": [], "flags": ["file_read_failure"], "extractor": "not_attempted"}, False
            else:
                extracted, hit = _extract_cached(Path(file_record["source_pdf"]), sha, cache, fingerprint,
                                                 settings.get("refresh_cache", False))
            extracted_by_sha[sha] = extracted
            cache_hits += hit
        extracted = extracted_by_sha[sha]
        header = extracted.get("pages", [{}])[0].get("text", "") if extracted.get("pages") else ""
        updated = finalize_match(file_record, patients, header)
        files[idx] = updated
        issues.extend(updated.get("match_issues", []))
        if (idx + 1) % 20 == 0 or idx + 1 == len(files):
            logger.info("Extracted/matched %s/%s; unique content=%s", idx + 1, len(files), len(extracted_by_sha))

    grouped = defaultdict(list)
    for file_record in files:
        grouped[file_record["content_key"]].append(file_record)
    ocr_paths, ocr_receipt = {}, {}
    if settings.get("ocr", "off") == "missing":
        if not settings.get("ocr_model_dir"):
            raise ValueError("Local OCR requires an explicit ocr_model_dir with predownloaded models")
        from .ocr_runner import prepare_ocr
        ocr_paths, ocr_receipt = prepare_ocr(files, extracted_by_sha, cache, fingerprint, settings)
        metadata["ocr_receipt"] = ocr_receipt
        write_json(output / "run_metadata.json", metadata)
    documents, sections, page_rows, mentions, coverage_rows = [], [], [], [], []
    for sha, group in grouped.items():
        # Respect configured root order, then stable lexical path. Prefer a
        # confidently matched alias if only one filename has a matching name.
        group.sort(key=lambda d: (not bool(d.get("patient_id")), roots.index(Path(d["source_root"]).resolve())
                                 if Path(d["source_root"]).resolve() in roots else len(roots), d["source_pdf"]))
        canonical = group[0]
        doc_id = canonical["document_id"]
        identities = {d.get("patient_id") for d in group if d.get("patient_id")}
        if len(identities) > 1:
            for d in group:
                d["patient_id"] = ""
                d["match_status"] = "ambiguous_duplicate_identity"
            issues.append({"issue_type": "duplicate_content_multiple_patients", "severity": "error",
                           "document_id": doc_id, "details": sorted(identities)})
        patient_id = canonical.get("patient_id", "")
        raw_extracted = extracted_by_sha[sha]
        extracted = json.loads(ocr_paths[sha].read_text(encoding="utf-8")) if sha in ocr_paths else raw_extracted
        normalized = normalize_document(extracted)
        normalized_pages = normalized["pages"]
        raw_path = output / "extracted" / f"{doc_id}.json"
        norm_path = output / "normalized" / f"{doc_id}.json"
        text_path = output / "normalized" / f"{doc_id}.txt"
        section_path = output / "sections" / f"{doc_id}.json"
        provenance = {"patient_id": patient_id, "document_id": doc_id, "source_pdf": canonical["source_pdf"],
                      "source_sha256": canonical["sha256"], "aliases": [d["source_pdf"] for d in group]}
        write_json(raw_path, {**raw_extracted, **provenance})
        write_json(norm_path, {**normalized, **provenance})
        write_text(text_path, "\n\f\n".join(f"=== PAGE {p['page']} ===\n{p.get('normalized_text', '')}" for p in normalized_pages))
        doc_sections = segment_document(normalized_pages, canonical["source_pdf"], patient_id, doc_id)
        for i, section in enumerate(doc_sections):
            section.update({"section_id": section.get("section_id") or f"{doc_id}_s{i + 1:05d}",
                            "patient_id": patient_id, "document_id": doc_id, "source_pdf": canonical["source_pdf"],
                            "text_path": relative_output(section_path, output), "text_reference": f"/sections/{i}/text",
                            "available_at": "", "cutoff_review_required": True})
            section["section_date"] = section.get("section_date") or section.get("document_date") or ""
            section["document_date"] = section["section_date"]
            section.setdefault("flags", [])
            page_numbers = {span["page"] for span in section.get("page_spans", [])}
            if not page_numbers:
                page_numbers = set(range(section["page_start"], section["page_end"] + 1))
            relevant_pages = [p for p in normalized_pages if p["page"] in page_numbers]
            sources = {p.get("normalized_text_source", "pdf_text_layer") for p in relevant_pages}
            section["text_source"] = next(iter(sources)) if len(sources) == 1 else "mixed"
            section["date_requires_review"] = section.get("date_source", "").startswith("local_ocr:")
            section["date_evidence_confidence"] = None
            if section["date_requires_review"]:
                date_page = next((p for p in relevant_pages if p["page"] == section.get("date_page")), None)
                if date_page and isinstance(section.get("date_line"), int):
                    line_map = date_page.get("normalized_line_map", [])
                    normalized_line = section["date_line"]
                    if 0 < normalized_line <= len(line_map):
                        ocr_line = line_map[normalized_line - 1]
                        ocr_lines = date_page.get("ocr_lines", [])
                        if 0 < ocr_line <= len(ocr_lines):
                            confidence = ocr_lines[ocr_line - 1].get("confidence")
                            section["date_evidence_confidence"] = confidence
                            if confidence is not None and confidence < 0.8:
                                section["date_uncertain"] = True
                                section["flags"].append("low_confidence_ocr_date")
            page_statuses = {p.get("extraction_status", "ok") for p in relevant_pages}
            unusable = {"failed", "empty", "text_layer_unusable"}
            if extracted.get("parse_status") in unusable:
                section["parse_status"] = extracted["parse_status"]
            elif page_statuses & unusable:
                section["parse_status"] = "partial"
            else:
                section["parse_status"] = section.get("parse_status", "ok")
            section.setdefault("clinical_stage", "unknown")
            section["leakage_risk"] = "flagged" if section.get("leakage_flags") else "unreviewed"
            for mention in section.get("mentioned_dates", []):
                mentions.append({"patient_id": patient_id, "document_id": doc_id, "section_id": section["section_id"],
                                 "source_pdf": canonical["source_pdf"], **mention,
                                 "text_path": section["text_path"], "text_reference": section["text_reference"]})
            sections.append(section)
        write_json(section_path, {**provenance, "sections": doc_sections})
        # A coverage ledger makes accidental dropped or multiply-assigned lines
        # visible independently of a section count. Blank separator lines may
        # be normalized; all retained nonempty lines must belong to a section.
        for page in normalized_pages:
            lines = page.get("normalized_text", "").splitlines()
            counts = Counter()
            for s in doc_sections:
                for span in s.get("page_spans", []):
                    if span["page"] == page["page"]:
                        counts.update(range(span["start_line"], span["end_line"] + 1))
            nonempty = [j for j, line in enumerate(lines, 1) if line.strip()]
            coverage_rows.append({"document_id": doc_id, "page": page["page"], "nonempty_lines": len(nonempty),
                                  "uncovered_lines": sum(counts[j] == 0 for j in nonempty),
                                  "overlapping_lines": sum(counts[j] > 1 for j in nonempty)})
            page_rows.append({"document_id": doc_id, "patient_id": patient_id, "source_pdf": canonical["source_pdf"],
                              "page": page["page"], "char_count": page.get("char_count", len(page.get("text", ""))),
                              "normalized_character_count": len(page.get("normalized_text", "")),
                              "extraction_status": page.get("extraction_status", "unknown"), "flags": page.get("flags", []),
                              "raw_extraction_status": page.get("raw_extraction_status", page.get("extraction_status", "unknown")),
                              "ocr_recommended": page.get("ocr_recommended", False), "ocr_status": page.get("ocr_status", "pending" if page.get("ocr_recommended") else "not_needed"),
                              "ocr_character_count": page.get("ocr_character_count", 0),
                              "ocr_mean_confidence": page.get("ocr_mean_confidence"),
                              "ocr_low_confidence_line_count": page.get("ocr_low_confidence_line_count", 0),
                              "analysis_text_source": page.get("analysis_text_source", "pdf_text_layer")})
        reliable_dates = sorted({s["section_date"] for s in doc_sections if s["section_date"] and not s.get("date_uncertain")})
        types = sorted({s["section_type"] for s in doc_sections if s["section_type"] not in {"unknown", "nonclinical"}})
        if len(types) == 1:
            document_type = types[0]
        elif types:
            document_type = "mixed"
        elif doc_sections and all(s["section_type"] == "nonclinical" for s in doc_sections):
            document_type = "nonclinical"
        else:
            document_type = "unknown"
        doc_status = extracted.get("parse_status", "failed")
        # PDF print/export/birth dates are never used as a container document date.
        pdf_date = doc_sections[0]["section_date"] if len(doc_sections) == 1 and not doc_sections[0].get("date_uncertain") else ""
        for file_record in group:
            documents.append({**file_record, "duplicate_of": "" if file_record is canonical else doc_id,
                              "page_count": extracted.get("page_count", 0), "page_start": 1 if normalized_pages else 0,
                              "page_end": extracted.get("page_count", 0), "extracted_character_count": extracted.get("extracted_character_count", 0),
                              "normalized_character_count": sum(len(p.get("normalized_text", "")) for p in normalized_pages),
                               "document_type": document_type,
                              "document_date": pdf_date, "date_status": "single_section" if pdf_date else "multiple_sections" if len(doc_sections) > 1 else "unknown",
                              "earliest_section_date": reliable_dates[0] if reliable_dates else "",
                              "latest_section_date": reliable_dates[-1] if reliable_dates else "",
                              "n_sections": len(doc_sections), "parse_status": doc_status,
                              "raw_parse_status": extracted.get("raw_parse_status", doc_status),
                              "ocr_attempted_page_count": extracted.get("ocr_attempted_page_count", 0),
                              "ocr_recovered_page_count": extracted.get("ocr_recovered_page_count", 0),
                              "ocr_character_count": extracted.get("ocr_character_count", 0),
                              "extractor": extracted.get("extractor", ""), "flags": extracted.get("flags", []),
                              "raw_text_path": relative_output(raw_path, output), "text_path": relative_output(text_path, output),
                              "sections_path": relative_output(section_path, output)})

    timeline = make_timeline(sections)
    manifest = []
    for patient in patients:
        pid = patient["patient_id"]
        docs = [d for d in documents if d.get("patient_id") == pid]
        unique = [d for d in docs if not d["duplicate_of"]]
        statuses = Counter(d["parse_status"] for d in unique)
        dates = sorted(t["date"] for t in timeline if t["patient_id"] == pid)
        manifest.append({"patient_id": pid, "has_inpatient_id": patient["has_inpatient_id"],
                         "has_outpatient_id": patient["has_outpatient_id"], "n_pdf": len(unique), "n_source_pdf": len(docs),
                         "n_parsed_pdf": statuses["ok"], "n_partial_pdf": statuses["partial"],
                         "n_readable_pdf": statuses["ok"] + statuses["partial"],
                         "n_ocr_pdf": sum(d["ocr_recovered_page_count"] > 0 for d in unique),
                         "n_unusable_pdf": statuses["text_layer_unusable"], "n_failed_pdf": statuses["failed"],
                         "n_empty_pdf": statuses["empty"],
                         "n_sections": sum(s["patient_id"] == pid for s in sections),
                         "earliest_document_date": dates[0] if dates else "", "latest_document_date": dates[-1] if dates else "",
                         "parse_status": "no_pdf_in_scope" if not unique else "ok" if statuses["ok"] == len(unique)
                         else "unusable" if not (statuses["ok"] or statuses["partial"]) else "partial",
                         "scope": settings.get("scope", "configured_roots")})
    # This is a restricted local linkage file. Hash pseudonyms do not anonymize
    # the source data and must not be advertised as anonymization.
    write_csv(output / "private" / "patient_linkage.csv", patients)
    write_csv(output / "patient_manifest.csv", manifest)
    write_csv(output / "document_index.csv", documents, DOCUMENT_FIELDS)
    write_csv(output / "section_index.csv", sections, SECTION_FIELDS)
    write_csv(output / "patient_timeline.csv", timeline, TIMELINE_FIELDS)
    write_csv(output / "date_mentions.csv", mentions)
    write_csv(output / "page_index.csv", page_rows)
    write_csv(output / "private" / "document_matching_evidence.csv", files,
              ["document_id", "patient_id", "source_pdf", "match_status", "match_method", "header_identifiers",
               "document_labelled_identifiers", "header_crosschecked", "identifier_conflict", "match_issues"])
    write_csv(output / "qc" / "ocr_queue.csv", [p for p in page_rows if p["ocr_recommended"]])
    write_csv(output / "qc" / "section_coverage.csv", coverage_rows)
    summary = build_qc(output, manifest, documents, sections, issues, page_rows, timeline)
    summary["uncovered_nonempty_lines"] = sum(r["uncovered_lines"] for r in coverage_rows)
    summary["overlapping_nonempty_lines"] = sum(r["overlapping_lines"] for r in coverage_rows)
    summary["extraction_cache_hits"] = cache_hits
    summary["ocr_cache_hits"] = ocr_receipt.get("cache_hits", 0)
    summary["raw_pdf_parse_status"] = dict(Counter(d["raw_parse_status"] for d in documents if not d["duplicate_of"]))
    summary["ocr_attempted_pages"] = sum(d["ocr_attempted_page_count"] for d in documents if not d["duplicate_of"])
    summary["ocr_recovered_pages"] = sum(d["ocr_recovered_page_count"] for d in documents if not d["duplicate_of"])
    summary["ocr_status"] = dict(Counter(p["ocr_status"] for p in page_rows if p["ocr_recommended"]))
    # Rehash the complete selected input inventory after processing. ZIP/XLSX
    # outside the requested CSV+PDF pipeline are not opened or modified.
    unchanged = sha256_file(csv_path) == csv_sha
    unverifiable = 0
    inventory = [{"kind": "cohort_csv", "source_path": str(csv_path), "sha256": csv_sha, "unchanged": unchanged}]
    verify = settings.get("verify_source_hashes", True)
    for d in documents:
        error = ""
        try:
            same = sha256_file(Path(d["source_pdf"])) == d["sha256"] if verify and d["sha256"] else None
        except OSError as exc:
            same, error = None, type(exc).__name__
        if verify and same is None:
            unverifiable += 1
        if same is False:
            unchanged = False
        inventory.append({"kind": "pdf", "document_id": d["document_id"], "source_path": d["source_pdf"],
                          "sha256": d["sha256"], "unchanged": same, "verification_error": error})
    write_csv(output / "source_inventory.csv", inventory)
    summary["source_hash_verification"] = "failed" if not unchanged else "partially_unverifiable" if unverifiable else "passed" if verify else "not_requested"
    summary["source_unverifiable_count"] = unverifiable
    summary["duration_seconds"] = round(time.perf_counter() - started, 3)
    write_json(output / "qc" / "cohort_summary.json", summary)
    write_csv(output / "qc" / "cohort_summary.csv", [{"metric": k, "value": v} for k, v in summary.items()], ["metric", "value"])
    metadata.update({"status": "complete" if unchanged else "failed_source_integrity", "finished_at": datetime.now().astimezone().isoformat(),
                     "summary": summary, "extraction_fingerprint": fingerprint})
    metadata["code_changed_during_run"] = any(sha256_file(Path(__file__).parent / name) != digest
                                            for name, digest in metadata["code_sha256"].items())
    write_json(output / "run_metadata.json", metadata)
    if not unchanged:
        raise RuntimeError("A raw input changed during processing; inspect source_inventory.csv")
    logger.info("Complete: unique PDFs=%s sections=%s timeline=%s elapsed=%.1fs", len(grouped), len(sections), len(timeline), summary["duration_seconds"])
    return summary
