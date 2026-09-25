# AAOCA management deterministic v1 — 2026-09-26

This tracked report contains aggregate results only. Patient-level tables and clinical excerpts remain under Git-ignored `data/derived/aaoca_management_rules_v1/` and were not sent to any external API or LLM.

## Cohort receipt

The completed `data/derived/v0.1_full` snapshot was independently validated before acceptance: 232 patients, 365 source documents, 342 canonical documents, 13,485 pages, 13,931 sections and 10,341 timeline events; validation returned 0 errors and 0 warnings.

The exception-only AAOCA relevance contract selected 230 `yes` patients and excluded 2 `uncertain` patients. Of the included cohort, 62 came from incomplete automatic exception judgments and 170 from the automatic nonexception contract. Human review remains 0/62 completed, so these are not clinician-confirmed AAOCA labels.

## Actual deterministic result

| `observed_management` | Patients | Share of 230 |
|---|---:|---:|
| `surgery` | 111 | 48.3% |
| `intended_surgery` | 11 | 4.8% |
| `conservative` | 20 | 8.7% |
| `unknown` | 88 | 38.3% |

The separate `actual_aaoca_surgery` result is 111 `yes`, 9 explicit `no`, and 110 `unknown`. The 11 weaker conservative/observation cases deliberately retain surgery status `unknown`; no-record cases were not converted to `no`.

The scan read 13,869 sections for included patients and produced 1,619 provenance-bearing evidence rows. Diagnostic catheterisation/angiography evidence occurs in 73 patients and is explicitly excluded from surgery. Forty-two completed non-AAOCA/unresolved operations across 41 patients are retained as negative-boundary evidence rather than silently discarded.

## Surgery events

There are 112 deduplicated AAOCA-related surgery events among 111 patients. One patient has two distinct completed events on different dates. Repeated operation, postoperative and discharge descriptions were attached to an event rather than counted as new surgery.

| Event date state | Events |
|---|---:|
| Exact day, no detected conflict | 108 |
| Exact day, conflicting dates in source evidence | 3 |
| Month precision only | 1 |

One hundred eleven events include a formal surgery-record section. The remaining event is supported by repeated historical/postoperative documentation of an outside-hospital AAOCA operation; its date is available only to month precision. All 112 events have postoperative evidence. Management confidence is high for 107 surgery patients and medium for 4 because of the three date conflicts and one month-only outside-hospital event.

Normalized procedure types overlap within an event. Counts were: coronary repair 76, unroofing 42, origin correction 34, ostial reconstruction 8, reconstruction/lysis 5, reimplantation/transfer 3, nonspecific anomaly repair 1, and adjunct pulmonary-artery plasty 16.

## Review queue and validation

The QC queue contains 193 issue rows covering exactly the 183 patients marked `review_required=True`. It includes 88 management-unknown rows, 66 OCR/date-review rows, 12 mixed intent/conservative trajectories, 11 completion-not-proven rows, 11 follow-up/observation-only rows, 3 within-record date-conflict rows, 1 multiple-surgery row and 1 partial-date row. Reasons overlap.

The management validator reopened source section JSON and verified every evidence character span, cohort membership, primary/supporting references, event/evidence consistency, date-state combinations, source hashes, metadata counts and review-queue coverage. It passed with 0 errors and 0 warnings. The complete repository suite passed all 74 tests.

## Interpretation limits

This is an evidence-first deterministic extraction, not a clinical gold standard. It is intentionally conservative about absent operations and diagnostic procedures, but OCR errors, nonstandard outside-hospital surgery names, complex same-admission operations and incomplete longitudinal records still require human review. No management annotation set has been completed or frozen, so no clinical accuracy metric is reported.
