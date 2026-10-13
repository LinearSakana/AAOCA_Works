# AAOCA management deterministic v1.1 correction audit

This tracked report contains aggregate results only. Patient-level tables, pseudonymous case decisions, and source excerpts remain in Git-ignored local directories.

## Why the correction was needed

The v1 rules were deliberately conservative, but a review of baseline `unknown` cases found four recurrent evidence forms that were too far apart or line-wrapped for the original local regex windows:

1. an AAOCA diagnosis followed later in the same discharge/progress section by multidisciplinary risk discussion and explicit refusal of surgery;
2. diagnostic angiography/catheterisation followed by a documented cardiac-surgical decision for observation and follow-up;
3. a multidisciplinary recommendation for surgery followed by family deferral or discharge before completion;
4. an unrelated congenital-heart operation in which the coronary anatomy was inspected and explicitly documented as not treated.

The correction keeps diagnostic catheterisation and unrelated operations outside AAOCA surgery. A detailed VSD/PFO/ASD operation without an explicit statement about AAOCA treatment remains insufficient for `conservative` and remains eligible for `unknown`.

## Audit design

The baseline contained 88 `unknown` patients. A local, Git-ignored audit generated a 33-case stratified sample across refusal/cancellation terms, multidisciplinary observation, generic intent, possible AAOCA-operation language, unrelated operations, ordinary follow-up, and no-candidate records. Targeted review also covered every patient whose patient-level state changed under the candidate rules and every patient hit by a newly introduced rule family.

Synthetic positive and negative controls cover:

- multidisciplinary AAOCA refusal versus refusal of an aortic-valve operation;
- a completed diagnostic procedure followed by explicit observation versus a plan merely to discuss next steps;
- explicit surgery recommendation/family deferral versus a diagnostic procedure called a “手术”;
- formal coronary inspection explicitly ending in no treatment versus VSD/PFO repair alone;
- a later post-workup observation decision superseding an earlier conditional surgery statement without asserting lifetime absence of surgery.

## Candidate v1.1 result

| State | v1 baseline | v1.1 candidate | Delta |
|---|---:|---:|---:|
| `surgery` | 111 | 111 | 0 |
| `intended_surgery` | 11 | 13 | +2 |
| `conservative` | 20 | 28 | +8 |
| `unknown` | 88 | 78 | -10 |

The transition matrix contains 3 `unknown -> intended_surgery`, 7 `unknown -> conservative`, and 1 `intended_surgery -> conservative` after later completed evaluation and follow-up decision. The separate `actual_aaoca_surgery` distribution changed from `111 yes / 9 no / 110 unknown` to `111 yes / 10 no / 109 unknown`: two previously unknown patients gained high-strength intraoperative coronary-not-treated evidence, while one baseline `no` and one intermediate-candidate `no` were downgraded because their only untreated wording was embedded in copied imaging history rather than a direct management or operative statement.

The operation layer is unchanged: 112 deduplicated AAOCA surgery events among 111 patients. The final candidate contains 1,653 provenance-bearing evidence rows and 211 QC rows. The unchanged surgery/event counts are an important regression check: none of the new refusal, observation, diagnostic, or unrelated-operation paths created a completed AAOCA surgery event.

The additive `overall_treatment_status` makes the AAOCA-specific boundary explicit. Its final distribution is 141 surgery, 12 intended surgery, 17 conservative and 60 unknown. The 141 surgery patients consist of 111 with completed AAOCA surgery evidence and 30 whose only completed operation evidence is non-AAOCA. This permits a VSD/PFO-only case to say that surgery actually occurred without changing `observed_management=unknown` or fabricating an AAOCA treatment relationship.

## Unknown provenance correction

The first correction batch intentionally left a detailed VSD/PFO/ASD operation as `unknown` when the record did not state whether the coronary anomaly was treated. The status is correct, but the v1 summary made such cases harder to review because an unrelated operation was not selected as primary evidence and the generic unknown queue could have an empty evidence list.

The final v1.1 candidate now uses a diagnostic-procedure assertion as the primary unknown evidence when available, otherwise the strongest `unrelated_completed` assertion. It also adds `unrelated_completed_operation_not_aaoca_management` to the patient review reasons and a dedicated `unrelated_operation_without_aaoca_management` QC row. Eighteen of the 78 remaining AAOCA-management `unknown` patients have this completed-other-operation boundary. They now have `overall_treatment_status=surgery`; their AAOCA-specific status, `actual_aaoca_surgery=unknown`, evidence assertions, and the AAOCA surgery-event table remain unchanged.

## Independent-review safety pass

Three read-only AGY tasks using `gemini-3.8-flash-high` independently reviewed case/prediction pairs, the rule implementation and public clinical abstraction literature. The case review supported the two intended relabels and the strict non-AAOCA boundary for VSD/PFO-only surgery. The literature review independently supported separating targeted AAOCA repair, surgical intent, diagnostic catheterisation, active surveillance and unrelated congenital-heart operations.

The code review identified concrete risks that were reproduced locally before acceptance. The final implementation therefore:

- compares equal-date decisions by document section and exact assertion offset instead of treating date equality as sufficient chronology;
- prevents routine follow-up text in the same section from overriding explicit surgery refusal;
- requires local AAOCA context for new observation/pending-operation rules and removes a duplicate generic intent hit when a more specific multidisciplinary rule already applies;
- rejects copied imaging boilerplate such as “please correlate with CT; follow up” as a clinical conservative-management decision;
- downgrades copied imaging labels containing “untreated” to medium strength, preserving a conservative stage while keeping the actual-surgery tri-state unknown;
- validates exact assertion spans, summary/evidence booleans, unrelated-operation summaries, overall-treatment state and every `actual_aaoca_surgery=no` claim's high-strength support.

## Final acceptance

- full repository suite: 78/78 tests passed;
- base `v0.1_full` validator: 0 errors, 0 warnings;
- candidate management-package validator: 230 patients, 1,653 evidence rows, 112 surgery events, 0 errors, 0 warnings;
- all changed patient-level states and all hits from new rule families were inspected locally against source sections;
- no patient content was placed in this report or in public literature queries.

These checks establish deterministic consistency and bounded regression behavior, not clinical accuracy. The AAOCA relevance cohort remains automatic because exception review is incomplete, and no frozen management gold set exists.
