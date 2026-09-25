# Structure and date investigation — v0.1

This report contains aggregate findings and synthetic examples only. Patient identifiers, source filenames containing names, dates from individual records, and clinical narrative remain in the local restricted intermediate artifacts. Raw PDFs were read without modification. No external API or hosted model was used.

## Observed templates

The initial investigation inspected all 23 sample PDFs, including readable records from multiple sample patients and continuation pages. It then replayed the structure parser against the complete first full text-layer run: **342 canonical PDFs / 13,485 pages**. Repeated byte-identical files are canonicalized by the main pipeline; the PDF count here is not the physical-file count.

The readable exports are bundles rather than one PDF per clinical document. Stable templates include admission/discharge titles, timestamp-prefixed progress and ward-round records, preoperative/operative documents, consultation records, and numerous consent/notification forms. Laboratory bundles contain multiple reports per page; `申请项目:` is the report boundary and `检验时间` marks the relevant result-date column. Some lab exports contain full timestamps, while others contain only complete calendar dates.

The browser print timestamp survives conservative text normalization at the page top. Navigation also contains the word `手术记录`, which must not create an operative document. Chinese text uses Unicode compatibility/Kangxi characters that require NFKC for dependable header matching. Some source pages have unusable text layers; visible numeric dates on those pages do not establish interpretable clinical documents.

## Implemented contract

`segment_document(pages, source_pdf, patient_id='', document_id='')` produces complete normalized-line coverage. Each section has its patient/document/source identity; section type and title; page and normalized-line boundaries; per-page end-exclusive character spans; raw evidence references; date precision and source; all mentioned dates with roles; uncertainty flags; and conservative title-based stage/leakage warnings.

Each normalized line belongs to exactly one section. Unknown preambles and damaged pages remain available. A damaged page starts an unknown section and prevents an earlier reliable date being propagated across it. A following readable continuation remains unknown until a new stable heading appears. Dates are never inherited from adjacent sections.

Date priority is title timestamp, explicit appropriate document fields, then an unambiguous laboratory time column. Birth, admission, print, planned-operation and sample-submission dates are retained as mentions. A discharge document may use its explicit discharge date. A calendar date without a time has day precision and an empty timestamp. Conflicting same-priority calendar dates remain unknown; differing same-day explicit times lower precision to day. A filename date is an uncertain fallback only for one recognized section without content dates, never for all documents in a multi-document bundle.

An OCR-recovered page can be segmented while retaining the original text-layer diagnostics. OCR-derived date evidence is prefixed `local_ocr:` and flagged `date_requires_review`; the section carries `ocr_unverified`. This is a provenance flag, not a validated OCR accuracy claim. OCR testing and full-run numbers are maintained separately by the main pipeline.

## Executed iterations and findings

1. Inspected the 23 sample PDFs and implemented template rules, unknown-content retention, page spans, explicit date-source extraction and synthetic regression fixtures.
2. Replayed the sample against actual normalized artifacts. Found that a lab report crossing a page boundary could pick up the browser print timestamp as a result date, or create a false date conflict. Added page-margin/provenance detection without deleting the original date mention.
3. Replayed all **342 canonical normalized PDFs**. Found **906 lab sections** whose previous date had been the print date. Their real result-date columns contained day-only values that the original datetime-only rule had missed. Extended the column rule to accept complete validated calendar dates while preserving day precision. This also recovered **617 previously undated laboratory sections**.
4. Replayed the complete corpus again with exact line-coverage verification and tightened short repeated-title handling. Distinct short progress records with different title dates must remain distinct even if their titles are identical; this recovered one separately dated progress section. Same-day conflicting explicit times are no longer silently resolved to the first time.

The following are **actual replay results on the full text-layer normalized artifacts**, before any later OCR run. They should not be mixed with physical-file counts or OCR-enhanced final-run counts.

| Metric | Count |
|---|---:|
| Canonical PDFs replayed | 342 |
| Pages in full text-layer run | 13,485 |
| Sections after corrected rules | 5,970 |
| Sections with a document date | 4,271 |
| Sections with unknown date | 1,699 |
| Exact normalized-line coverage errors | 0 |
| Date evidence mistakenly taken from normalized line 1 | 0 |
| Conflicting document calendar dates retained as unknown | 25 |
| Same-day conflicting explicit times lowered to day precision | 1 |

| Section type | Count |
|---|---:|
| progress | 1,854 |
| laboratory | 1,901 |
| administrative | 975 |
| surgery_related | 286 |
| admission | 129 |
| discharge | 126 |
| consultation | 116 |
| unknown | 583 |

| Accepted date source | Count |
|---|---:|
| Title timestamp | 2,140 |
| Laboratory result-date column | 1,900 |
| Explicit record date | 125 |
| Explicit discharge date | 78 |
| Explicit record time | 27 |
| Explicit consultation time | 1 |

The old full-run artifacts had 5,969 sections and 3,652 nonempty dates; those dates included the 906 incorrect print-date assignments. Higher date coverage alone would therefore have been a misleading quality measure. The replay left one laboratory section without a non-print date mention. These results prove structural coverage and that specific observed date bugs were corrected; they are not a clinician-validated segmentation or date-accuracy benchmark.

## Remaining observed failure modes

1. **Unusable Chinese text layers.** Numeric remnants can still look like valid dates. There are 318 sections carrying `unusable_text_layer` in this text-only replay; they remain unknown and undated. Local OCR is handled separately and requires review.
2. **A readable continuation follows a damaged page.** The original header may be lost. There are 122 `continuation_after_damaged_page` sections; guessing the preceding document would create unsupported associations.
3. **Administrative forms often lack a dependable creation date.** Signature dates, planned-operation dates and admission dates are not interchangeable. These sections are retained without forcing dates.
4. **Different explicit document dates occur within a section.** The replay found 25 such sections. They remain unknown until template interpretation or source review resolves them.
5. **Date precision differs across otherwise similar lab exports.** Day-only dates are usable for ordering by day but cannot establish an exact within-day prediction cutoff.
6. **Titles wrap or appear beside patient metadata.** Current boundaries use stable title lines. Metadata immediately before a new title may remain in the preceding section. Complete page/line evidence is retained, but perfect document ownership of every metadata line is not claimed.
7. **Repeated consent-form headings and genuinely separate copies coexist.** Very close repeated exact headings are merged conservatively; longer repeated forms remain separate. No clinical uniqueness is inferred from textual similarity.
8. **Report and outcome semantics differ.** `surgery_related` includes planning, discussion, consent-adjacent material and operation documents; it is not an `observed_management=surgery` label. A lab result-column time is not automatically a signed report-publication time.
9. **No independent ultrasound/follow-up template was identified in the readable text-only sections of this replay.** Such clinical information can occur inside narrative or unreadable pages; the zero count is not evidence of absent care.

## Validation and next work

Nineteen synthetic unit tests currently cover navigation exclusion, birth/admission/print-date separation, cross-page coverage, multiple lab reports on one page, day-only laboratory dates, conflicting dates and times, damaged-page boundaries, duplicate headings, different-day short progress notes, invalid/partial dates, filename scope, empty pages, OCR provenance, administrative narrative false positives, and unambiguous versus ambiguous OCR date/time joins. They contain no patient data.

The subsequent **20-page local OCR probe** was also replayed. Two admission records had the observed OCR form `YYYY-MM-DDHH:MM`, with the space between the two-digit day and two-digit hour missing. A bounded parsing alternative now recognizes that form without modifying the normalized text or its offsets. Ambiguous three-digit day/hour joins are still unknown. This recovered **2 OCR-derived explicit document dates**, both carrying `local_ocr:` provenance and `date_requires_review`; it does not establish that all OCR dates are accurate. The probe's 20 OCR pages and 785 text-layer pages produced 400 sections, including 262 sections with a date after this repair. Those probe counts are separate from the complete text-only replay above and any later full OCR run.

Next, review OCR-derived boundaries and dates separately, build a small clinician-reviewed document-boundary/date reference set, and add a limited number of wrapped-heading rules only when their failure frequency and false-positive risk are measured. Keep day-level cutoffs conservative and retain missing timestamps rather than inventing an event time.
