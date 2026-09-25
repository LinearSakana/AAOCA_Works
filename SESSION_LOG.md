# Session log — 2026-09-25 — AAOCA text pipeline v0.1

## Scope and privacy

Read `CONTEXT.md` first and treated it as the project contract. Inspected `data/sample_list/AAOCA_患者病例_清洗后.csv`, `data/sample_raw`, and `E:/Kenkyu-Shiryou/AAOCA Cases` read-only. No original file was edited. No patient content was sent to an external API; no LLM was used. Public Python packages and public OCR model weights were downloaded separately from patient processing, then all inference ran locally.

## Work completed

1. Audited the cohort CSV, sample PDFs and all available PDFs. Confirmed 232 cohort rows, 365 PDF paths, 342 unique contents, 23 sample/original exact duplicates, 232 record bundles and 110 laboratory bundles.
2. Implemented deterministic patient pseudonyms, exact filename/identifier matching, stable hospital URL header matching, identity conflict quarantine, source hashing and exact duplicate retention/canonicalization.
3. Implemented page-preserving PyMuPDF extraction with off-MediaBox recovery, geometry/paint diagnostics, quality statuses, vector-outline detection and pypdf exception fallback.
4. Diagnosed the Chrome/Quartz failure mode: visible Chinese is stored as vector outlines. Compared PyMuPDF/pypdf/pdfplumber and confirmed none can recover those semantics from the text layer.
5. Implemented reversible normalization with raw/OCR separation, Unicode/space cleanup, conservative browser-chrome removal, removed-line receipts and normalized-to-source line maps.
6. Installed RapidOCR/ONNX Runtime/OpenCV locally, prepared SHA-pinned PP-OCR v6 models, and added explicit local-only OCR with line geometry, confidence, provenance, atomic document caches and resumable process workers.
7. Compared PP-OCR v4/v5/v6 on the same 12-page set plus a progress-note control. Kept v6 based on aggregate speed and proxy results. Blocked network calls during an inference verification.
8. Ran a 20-page OCR integration probe, then processed all 8,216 target pages. Recovered nonempty OCR text on 8,202 pages; 14 stayed empty. The complete OCR pass took 8,796.803 seconds.
9. Implemented rule-based document/section segmentation, date evidence/precision, mentioned-date roles, page/line/character spans, unknown-section retention, clinical-stage hints and leakage warnings.
10. Iterated after real failures: fixed cross-line identifier parsing that had falsely quarantined 43 PDFs; separated historical internal IDs from the stable export envelope; removed browser print-time contamination from 906 laboratory sections; supported day-only laboratory dates; prevented short repeated progress headings with different dates from merging; and handled a bounded OCR-joined date/time form.
11. Built patient/document/page/section indexes, patient timeline, cutoff export, source inventory, private linkage evidence and automated QC tables.
12. Added an independent artifact validator and synthetic/end-to-end tests. Fixed unreadable-file empty-SHA grouping, final hash permission handling, output/cache overlap, nested link-to-raw protection, duplicate-content identity conflicts and failed-run receipts.
13. Rebuilt the final outputs using all OCR caches in 73.159 seconds. Verified source hashes, code stability during the run, section coverage and all cross-table/artifact references.

## Final data facts

- 231/232 patients have a matched PDF; 341/342 unique PDFs match the cohort.
- One patient has no PDF in scope; one unique PDF is not in the cohort.
- Raw text-layer status: 142 ok, 1 partial, 198 unusable for Chinese, 1 empty.
- Effective status after targeted OCR: 142 native ok, 199 OCR/partial, 1 empty.
- 13,485 pages; 8,102,527 raw text characters; 7,732,111 OCR characters; 13,261,480 normalized characters.
- 13,234 sections: 4,650 progress, 3,779 laboratory, 2,698 administrative, 709 surgery-related, 374 consultation, 367 unknown, 333 admission and 324 discharge.
- 9,725 dated sections; 3,509 unknown/uncertain dates; 5,454 OCR-derived dated sections require review.
- 9,704 patient timeline events across 231 patients.
- Section coverage errors: 0 uncovered nonempty lines and 0 multiply assigned nonempty lines.
- Source integrity verification passed. Independent output validation passed with 0 errors/0 warnings. All 50 tests passed.

## Files created or changed

- Project/config: `pyproject.toml`, `requirements.txt`, `requirements-ocr.txt`, `.gitignore`, `config/pipeline.sample.json`, `config/pipeline.full.json`, `config/pipeline.ocr.json`.
- Package: `src/__init__.py`, `src/aaoca_pipeline/__init__.py`, `__main__.py`, `io_utils.py`, `matching.py`, `extraction.py`, `local_ocr.py`, `ocr_runner.py`, `normalization.py`, `structure.py`, `timeline.py`, `quality_control.py`, `pipeline.py`, `enrichment.py`.
- Validation: `scripts/validate_outputs.py`, `tests/test_matching.py`, `tests/test_extraction.py`, `tests/test_structure.py`, `tests/test_pipeline.py`.
- Documentation: `README.md`, `reports/matching_investigation.md`, `reports/extraction_investigation.md`, `reports/structure_investigation.md`, `reports/validation_iteration_02_full_text.json`, `reports/validation_v0.1_full.json`, `reports/pipeline_v0.1_summary.md`, `SESSION_LOG.md`.
- Public models: `models/rapidocr/*` for the selected v6 runtime and `models/ocr_benchmark/{v4,v5,v6}/*` for comparison.
- Derived data: `data/derived/v0.1_full/`; development iterations and caches under `data/derived/iteration_*` and `data/derived/extraction_cache/`.

All data/model/scratch/output directories are excluded from Git by `.gitignore`; project reports contain only aggregate counts and anonymous artifact IDs.

## Commands actually run for final acceptance

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m aaoca_pipeline --config config/pipeline.ocr.json
python -X utf8 scripts/validate_outputs.py data/derived/v0.1_full --report reports/validation_v0.1_full.json
python -X utf8 -m aaoca_pipeline --config config/pipeline.ocr.json --before 2024-01-01
```

## Remaining issues

- OCR transcription, section boundaries and dates need a clinician-reviewed reference set; current checks establish software and provenance integrity, not medical correctness.
- Fourteen OCR pages remain empty; 28,558 OCR lines across 2,643 pages have model confidence below 0.8.
- Laboratory table cell relationships are not reconstructed in v0.1.
- 3,509 sections have unknown/uncertain dates and 367 have unknown type.
- `available_at` and clinically valid prediction cutoffs remain unresolved; outcome-containing narrative must be excluded/reviewed before modeling.
- The unmatched PDF, missing patient PDF and identifier discrepancies require source-owner reconciliation.
- Clinical management extraction was left for the next iteration; no proposed/planned procedure has been mislabeled as completed surgery.

## 2026-09-25 — Gold Set annotation and evaluation extension

Read the current context, pipeline output/schema, validation code, tests and aggregate reports before implementation. Kept original PDF files and existing `data/derived/v0.1_full` output read-only. Added `gold_common.py` (SHA/page anchored stratified sampling, annotation checks, freeze), `gold_review.py` (loopback-only PDF-page review desk), `gold_evaluate.py` (text, boundary, section, type/subtype, date and failure metrics), `scripts/gold_set.py`, synthetic tests, a plain-language review guide and an evaluation specification. `README.md` and an aggregate sampling report were updated in the same batch.

Ran the sampler on the real completed output with seed `20260925`: 48 pages across four equal native/OCR × record/lab strata, 24 routine and 24 challenge pages, 42 unique PDF contents and 41 pseudonymized patients. Stored manifest only under Git-ignored `data/gold_sets/aao_pdf_pages_v1/`; sample ID `81f579c39633ed326ca5`. No patient text was copied into tracked files. The sampled page labels are still parser predictions, not gold annotations.

The synthetic tests verify exact edit distance, four-stratum sampling, completion validation, annotation freezing and digest tamper detection, boundary/section matching, print-date confusion attribution, and fair-comparison guards. Acceptance: `python -X utf8 -m unittest discover -s tests -v` passed 62 tests; `scripts/validate_outputs.py data/derived/v0.1_full` passed with 0 errors/0 warnings; `gold_set.py validate` found 48 sampled and 0 completed pages. A real local Playwright browser loaded the review page and PDF image, showed two predicted sections, saved a draft, and displayed without horizontal overflow at 900 px and 1280 px. The browser initially exposed a missing token on CSS/JS requests; it was fixed and a repeat check reported 0 console errors. The disposable draft and browser artifacts were removed after the smoke check. No real clinical accuracy can be reported until human reviewers finish and freeze an annotation revision.

### Follow-up hardening batch

Added same-PDF neighboring-page navigation to the review desk so reviewers can inspect dates at the start of a section that crosses a sampled page edge, while the annotation target remains the sampled page. Split source comparison into fixed baseline native/OCR strata and the evaluated run's actual extraction source. Extended synthetic tests to compare a deliberately improved parser run with completely renumbered document IDs against the identical frozen sample, and to confirm that uncertain text/type/subtype/date and unreviewable pages affect only their eligible score denominators. Documentation was updated with the new review navigation and grouping semantics. A fresh rerun of the real sampler produced the exact same `sample_id` and 48 unit records. A browser check loaded PDF page 18 as context while keeping sample page 17 as the annotation target, returned to the sample page, and reported 0 console errors; temporary browser artifacts were removed.

Acceptance after this batch: all 63 synthetic/end-to-end tests passed; working annotation validation still reports 48 sampled pages, 0 saved/complete pages. Gold accuracy remains pending actual PDF review.

### Failure-analysis usability batch

Added direct review-desk jump by anonymous `unit_id` or 1-based sample position, so `failures` rows can be opened without paging through the whole sample. Corrected date-confusion attribution when gold confirms no event date but the parser adopts an annotated print/historical/planned date. Failure-mode aggregates now count multiple missed/extra boundaries by occurrence rather than by page while preserving page-level failure rows. Updated guides and added a synthetic regression for the no-event-date print case.

Acceptance: all 64 tests passed. A real browser opened the second sample by `&unit=pg_...`, jumped to sample 48 through the header input, loaded PDF images, and reported 0 console errors. Browser artifacts were removed. `gold_set.py validate` still reports 48 sampled, 0 saved, 0 complete; no real labels were invented for testing.
