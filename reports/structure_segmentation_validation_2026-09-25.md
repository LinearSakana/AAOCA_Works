# Section segmentation validation (2026-09-25)

This check reran `segment_document` against the 342 saved `data/derived/v0.1_full/normalized/*.json` files and compared section starts with the matching existing section JSON files. It did not rerun PDF extraction or OCR. The report contains aggregate counts only.

| Measure | Existing output | Revised segmentation |
|---|---:|---:|
| Sections | 13,234 | 13,931 |
| `unknown` sections | 367 | 0 |
| `nonclinical` sections | 0 | 367 |
| `laboratory` sections | 3,779 | 4,200 |

All 13,234 existing section starts remain present. There are 697 new starts: 421 `申请项目:` boundaries with leading layout symbols, 156 structured outpatient forms, 36 dated `调整抗生素记录` headings, and 84 exact administrative or OCR consultation headings. Every laboratory section contains at most one recognized `申请项目:` boundary. Of the new outpatient starts, 153 have the full `主诉`、`现病史`、`治疗计划` field combination. Three further starts separate a later visit with a distinct visit timestamp, department, complaint, and history; this resolves three previously conflicting outpatient document dates. All 156 outpatient sections have document dates. All retained nonempty normalized lines have exactly one section span; the coverage check found no gaps or overlaps.

Of the 4,200 laboratory sections, 4,172 have a specific or evidence-supported title and 28 remain blank. Blank project names are recovered as `血气分析` only with a strong blood gas analyte combination; single-marker names are kept as titles, while mixed or insufficient evidence remains untitled.

The 367 `nonclinical` sections consist of recognized navigation/export chrome, blank damaged pages, and three short institutional/demographic header fragments after damaged pages. Their damaged-page flags remain available for QC. The saved derived output was used only as a baseline; these revised sections were validated in memory and have not replaced `data/derived/v0.1_full` artifacts.

The synthetic test suite passed 59 tests, including multi-report laboratory boundaries, title-free outpatient forms, OCR consultation titles, administrative promises, subtype assignment, source line coverage, and end-to-end CSV/timeline export. The corpus comparison tests structural consistency and observed patterns; it is not a clinician-reviewed label set, so subtype accuracy for ambiguous OCR remains subject to review.
