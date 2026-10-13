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
| `conservative` | 20 | 29 | +9 |
| `unknown` | 88 | 77 | -11 |

The transition matrix contains 3 `unknown -> intended_surgery`, 8 `unknown -> conservative`, and 1 `intended_surgery -> conservative` after later completed evaluation and follow-up decision. The separate `actual_aaoca_surgery` distribution changed from `111 yes / 9 no / 110 unknown` to `111 yes / 12 no / 107 unknown`; all three new `no` values have explicit coronary-not-treated evidence rather than an inference from missing surgery records.

The operation layer is unchanged: 112 deduplicated AAOCA surgery events among 111 patients. The candidate contains 1,656 provenance-bearing evidence rows and 191 QC rows. The unchanged surgery/event counts are an important regression check: none of the new refusal, observation, diagnostic, or unrelated-operation paths created a completed AAOCA surgery event.

## Acceptance at correction batch 1

- full repository suite: 77/77 tests passed;
- base `v0.1_full` validator: 0 errors, 0 warnings;
- candidate management-package validator: 230 patients, 1,656 evidence rows, 112 surgery events, 0 errors, 0 warnings;
- all changed patient-level states and all hits from new rule families were inspected locally against source sections;
- no patient content was placed in this report or in public literature queries.

These checks establish deterministic consistency and bounded regression behavior, not clinical accuracy. The AAOCA relevance cohort remains automatic because exception review is incomplete, and no frozen management gold set exists.
