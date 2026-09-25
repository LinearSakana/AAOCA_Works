# Patient/PDF matching investigation

Local read-only run, 2026-09-25. No raw names or hospital identifiers appear in this report.

```json
{
  "rows": 232,
  "sources": 365,
  "unique": 342,
  "cohort_issues": {
    "identifier_conflict": 1
  },
  "source_status": {
    "matched": 364,
    "unmatched": 1
  },
  "unique_status": {
    "matched": 341,
    "unmatched": 1
  },
  "unique_match_issues": {
    "unmatched_file": 1,
    "document_identifier_mismatch": 13,
    "header_identifier_mismatch": 6,
    "filename_name_mismatch": 3
  },
  "header_crosschecked_unique": 317,
  "patients_matched": 231,
  "patients_without_pdf": [
    "p_2f07ba0d68173d8b"
  ],
  "unmatched_document_ids": [
    "doc_edd2b99f8c5c4a88333f"
  ],
  "filename_recovered_documents": [
    "doc_ee8af3ca2b153b4f1f58",
    "doc_219c00b8c9aa935238bf",
    "doc_246155678bd909300e88"
  ]
}
```

The 23 sample PDFs are byte-identical copies of originals. All 365 source paths remain inventoried; 342 canonical contents are available for parsing. Root order gives original data precedence. Exact filename names initially match 338 of 342 originals. Three further originals are recovered using exact hospital header URL identifiers, despite filename names differing from the cohort. One PDF contains hospital identifiers absent from the cohort and remains unmatched. No fuzzy-name merge is used.

Two distinct CSV rows share one non-placeholder outpatient identifier. Unique inpatient identifiers distinguish them. Six original PDFs from four patients have outpatient header IDs that differ from the CSV; their exact inpatient IDs and filename names agree, so association is retained with an explicit identifier-conflict warning. These discrepancies require source reconciliation and are not silently corrected.

A source may be matched by exact filename only where the text header is absent or not decoded. `header_crosschecked` distinguishes these cases. Conflicting known patients or multiple stable header identities yield an empty patient ID and `ambiguous` status, which must exclude them from patient timelines. Synthetic tests also cover arbitrary clinical-number false matches, unknown inpatient conflicts, shared outpatient ambiguity, duplicate sources, stable IDs under row reorder, placeholders, and same-name distinct patients.

Patient IDs are deterministic SHA256 pseudonyms based primarily on the unique inpatient ID. They remain stable under CSV row reordering. They are not privacy-safe public identifiers and neither hashes nor local outputs are claimed to be anonymised. Original IDs are never overwritten. The matching module has no network calls.

Actual iteration: a first 365-source run found that a naive multiline labelled-ID regex consumed the date following an empty inpatient label, falsely quarantining 43 PDFs. The implementation now limits labelled IDs to the same line and explicitly excludes date tokens. A second complete matching run confirms the corrected numbers above; regression tests cover this observed case. All 14 matching tests pass.

Final matching validation uses the recovered text first page from all 365 source records in `iteration_02_full_text`, reusing 342 extraction JSON files. Historical/truncated internal document identifiers are reported separately from the stable patient envelope URL; only conflicting known patient identities are quarantined. The current matching suite contains 16 passing tests.
