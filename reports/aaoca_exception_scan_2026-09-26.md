# AAOCA relevance exception scan — 2026-09-26

This report contains aggregate counts and pseudonymous design facts only. The local review package contains direct identifiers and clinical excerpts under Git-ignored `data/review/`; none are copied into this report.

The deterministic patient-level scan read the completed `data/derived/v0.1_full` snapshot after the independent artifact validator passed with zero errors and zero warnings. The review question is whether AAOCA or a corresponding coronary-origin abnormality ever became a meaningful diagnostic direction, not whether AAOCA was ultimately confirmed.

## Actual run

| Metric | Count |
|---|---:|
| Patients scanned | 232 |
| Automatic `yes` | 230 |
| Automatic `no` | 0 |
| Automatic `uncertain` | 2 |
| Exception patients sent to human review | 62 |
| Nonexception patients omitted from the human deliverable | 170 |
| Required-priority exceptions | 2 |
| High-priority exceptions | 46 |
| Medium-priority exceptions | 14 |
| Selected evidence rows for exception patients | 654 |

The two automatic `uncertain` cases are materially different: one patient has no PDF in the configured input scope; the other has one empty record PDF plus an OCR-recovered laboratory bundle whose nonclinical header contains a coronary-origin diagnosis, but no clinical narrative that establishes the diagnostic process. No patient was automatically classified `no`.

## Exception reasons

Reason counts overlap because one patient may need review for more than one issue.

| Reason | Patients |
|---|---:|
| Conflicting coronary-origin descriptions | 28 |
| Single-coronary/complex-CHD scope boundary | 19 |
| Pulmonary-origin scope boundary | 14 |
| Normal and abnormal origin stated for the same vessel | 14 |
| Tentative evidence only | 3 |
| Missing source documentation | 1 |
| Evidence only in nonclinical/laboratory content | 1 |
| Single evidence section | 1 |
| Sparse nonspecific label | 1 |
| Sparse OCR-only evidence | 1 |
| High origin without more specific anatomy | 1 |
| Normal origin plus nonspecific positive label | 1 |

## Interpretation and limits

The 230 automatic `yes` values are evidence-routing results, not clinician-confirmed labels. The exception queue intentionally includes cases that remain `yes` under the project definition but merit human review because their anatomy conflicts across documents or sits near the intended cohort boundary. A later normal result does not reverse `yes` when the record shows a real AAOCA workup.

The review files are generated with `ruleset_version=aaoca_exception_rules_v1`, retain source table hashes, and do not modify the source pipeline snapshot. Human final judgments are blank until review. No LLM was used; `AaocaEvidenceExtractor` is only an interface for a future separately authorized local middleware.
