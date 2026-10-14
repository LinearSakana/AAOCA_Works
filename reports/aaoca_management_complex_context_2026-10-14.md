# AAOCA management v1.2: complex-procedure context and full-rerun acceptance

## Scope

This batch extends the correction audit from 2026-10-13. The four AAOCA management states retain their meaning. Additive research fields describe actual competing procedures, coronary handling within each procedure, and reasons to prioritize complex cases. They are not treatment recommendations, severity scores, or causal comorbidity labels.

## Evidence-driven changes

- Separate completed cardiac surgery, therapeutic catheter intervention, noncardiac surgery and unclassified operations using named procedure evidence.
- Retain procedure-specific coronary handling with evidence IDs. Missing handling, explicit non-treatment, anatomical assessment without intervention, concomitant AAOCA repair and uncertain coronary manipulation are distinct.
- Preserve coronary Button transfer during complex congenital repair as `context_only` unless AAOCA-targeted treatment is established.
- Retain pending multidisciplinary decisions as context without promoting them to intent or conservative care.
- Correct the mixed-procedure branch: a named septal/PDA closure or balloon valvuloplasty plus angiography contains treatment. Nine additional patients now have a documented overall therapeutic procedure, with their AAOCA-specific management unchanged.
- Decode new JSON fields in LLM requests, route high-priority complex cases, and prohibit `context_only` from establishing AAOCA surgery.

## Initial v1.2 candidate

230 included patients; 1,608 evidence rows; 112 AAOCA surgery events among 111 patients. The AAOCA status distribution remains 111 surgery / 13 intended surgery / 28 conservative / 78 unknown. Overall therapeutic-procedure status becomes 150 surgery / 11 intended surgery / 17 conservative / 52 unknown. Actual AAOCA surgery remains 111 yes / 10 no / 109 unknown.

The candidate records 72 patients with another cardiac therapeutic procedure, 50 with diagnostic procedures but no other cardiac therapeutic procedure documented, and 108 with neither category documented. Complex-case priority is 26 high / 74 medium / 130 routine. These strata may overlap AAOCA surgery and must not be interpreted as mutually exclusive treatment arms.

All 15 focused management/context/LLM tests pass. Source-bound candidate validation passes with 0 errors and 0 warnings. The new cases test missing coronary handling, noncardiac operations, combined therapy/angiography, ASO Button transfer, different operation dates, intraoperative versus copied imaging evidence, and pending decisions.

The batch checkpoint subsequently passed 86/86 repository tests and 16/16 focused tests, including fabricated-context rejection. The final mixed-procedure implementation retains both diagnostic and therapeutic assertions; the final rerun will therefore retain the previously suppressed angiography evidence as well as the newly recovered therapy. The initial candidate's 1,608-row count is not the final output count.

## Independent audit status

Three read-only AGY tasks were dispatched with `gemini-3.8-flash-high` and unrestricted tool access as requested. The first attempt did not yield completed audits: two worker processes were interrupted and one reported a temporarily unavailable local proxy. After checking that the proxy listener had recovered and confirming no agent edits, all three conversations resumed with the v1.2 candidate. Their final acceptance and any consequent corrections will be recorded below; dispatch alone is not audit completion.

Patient content, prompts, audit outputs and temporary artifacts remain Git-ignored under `data/`, `scratch/` and `.agy-staff/`.

## Independent audit acceptance and correction batch 5

All three resumed read-only audits completed: 10 complex-operation cases, 10 decision-trajectory cases, and 16 stratified random cases (36 observations, 33 unique patients). The requested model was `gemini-3.8-flash-high`; no more than three ran concurrently, and the main implementation continued while they worked. Reviewers received read-only instructions without tool restrictions. The companion's concurrent-worktree warning matched the host's own three modified code/test files; inspection found no additional agent edits.

Accepted findings were checked in the original local sections, not imported as labels:

- Recover final no-indication decisions far from an unambiguous AAOCA diagnosis; retain competing-diagnosis and conditional-language guards.
- Recover wrapped refusal/deferral text and assign unresolved surgical intent a research-review reason.
- Correct anatomical-subtype bleed across numbered VSD/PFO procedure names.
- Preserve operative coronary anatomy/exploration without asserting repair or non-treatment.
- Recover actual catheter valve implantation, vascular stenting, ablation and pericardial operations, distinct from pure diagnostic catheter insertion.

Rejected recommendations included forcing every conservative case to `actual_aaoca_surgery=no`, treating a persistent diagnosis or omitted coronary treatment as proof of non-treatment, inferring AAOCA purpose for pulmonary-artery translocation without explicit support, and equating research-review priority with clinical risk. The audit is not clinician adjudication; its self-reported accuracy/confusion matrix is not used as a performance estimate.

Acceptance candidate: 230 patients, 1,695 evidence rows, 112 AAOCA events, 340 QC rows. AAOCA status is 111 surgery / 11 intended / 31 conservative / 77 unknown; overall treatment is 158 / 9 / 17 / 46; actual AAOCA surgery is 111 yes / 14 no / 105 unknown. Other cardiac therapy is documented in 85 patients. Research priority is 32 high / 86 medium / 112 routine.

Compared with the original v1 output, 8 unknown cases become conservative, 3 become intended surgery, and 3 prior intended cases become conservative after a documented later decision. All 112 AAOCA event patient/date/type/precision/status tuples are unchanged. All 91 repository tests passed; the final focused suite passed 21/21 and source-bound candidate validation returned 0 errors/0 warnings. Full formal-output rerun follows this checkpoint.
