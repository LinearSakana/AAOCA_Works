"""Evidence-backed research strata for competing procedures and unclear AAOCA care.

These fields describe documented procedures, not causal comorbidity or surgical
indications.  Missing coronary handling remains ``not_documented``.  The context
objects are evidence-level observations, deliberately not extra surgery events.
"""

from __future__ import annotations

import json
import re


CONTEXT_FIELDS = [
    "other_cardiac_procedure_status",
    "other_procedure_modes",
    "other_procedure_categories",
    "aaoca_handling_during_other_procedure",
    "other_procedure_contexts",
    "management_complexity_flags",
    "management_context_evidence_ids",
    "complex_case_review_priority",
    "complex_case_review_reasons",
]
CONTEXT_LIST_FIELDS = set(CONTEXT_FIELDS) - {
    "other_cardiac_procedure_status",
    "aaoca_handling_during_other_procedure",
    "complex_case_review_priority",
}

# Require a treatment action in the procedure name, rather than diagnosing a
# competing condition from a broad context window or routine operative language.
CATEGORY_PATTERNS = [
    ("septal_defect_repair", r"(?:AVSD|VSD|ASD|PFO|房室间隔缺损|室间隔缺损|房间隔缺损|卵圆孔).{0,12}(?:修补|封堵|关闭)"),
    ("valve_procedure", r"(?:TV|MV|AV|PV|三尖瓣|二尖瓣|主动脉瓣|肺动脉瓣).{0,10}(?:整形|成形|置换|扩张|修补|植入)|Ross手术"),
    ("outflow_or_pulmonary_artery_procedure", r"(?:流出道|肺动脉).{0,14}(?:疏通|重建|扩大|成形|移位|转位|环缩|拆除)"),
    ("ductus_or_aortic_arch_procedure", r"(?:PDA|动脉导管未闭|COA|主动脉缩窄|主动脉弓).{0,12}(?:关闭|封堵|结扎|纠治|修补|扩大)"),
    ("pulmonary_venous_repair", r"(?:PAPVC|TAPVC|肺静脉异位引流).{0,10}(?:纠治|矫治|修补)"),
    ("complex_congenital_repair", r"Switch|\bASO\b|动脉调转|大动脉转位.{0,8}(?:纠治|矫治)|Ross手术|Rastelli|Fontan|Glenn|TOF.{0,8}(?:纠治|根治)"),
    ("other_vascular_procedure", r"血管环.{0,8}(?:纠治|切断)|(?:锁骨下动脉|LSA|LCC|VA|大动脉瘤).{0,20}(?:移植|吻合|修补)"),
    ("vascular_stent_procedure", r"(?:血管|动脉|静脉).{0,12}支架|支架.{0,8}植入"),
    ("other_coronary_procedure", r"冠(?:状动)?脉瘤.{0,8}(?:修补|切除)|冠(?:状动)?脉瘘.{0,8}(?:封堵|结扎|修补)"),
    ("electrophysiology_procedure", r"射频消融|冷冻消融|起搏器.{0,8}(?:植入|更换)"),
    ("pericardial_procedure", r"心包.{0,8}(?:引流|剥脱|切开|开窗|切除)"),
    ("noncardiac_procedure", r"鞘状突|鞘膜|阴囊|阑尾|胸壁.{0,8}(?:切除|清创)|皮瓣|皮肤|皮下组织|软组织病损|纵[膈隔]囊肿"),
]
COMPILED_CATEGORIES = [(name, re.compile(pattern, re.I)) for name, pattern in CATEGORY_PATTERNS]
COMPLEX_RELATION_CATEGORIES = {"complex_congenital_repair", "other_coronary_procedure"}


def _list(value: object) -> list:
    if isinstance(value, list):
        return value
    return json.loads(str(value)) if value else []


def _true(value: object) -> bool:
    return value is True or str(value).lower() in {"true", "1", "yes"}


def procedure_modes_and_categories(name: str) -> tuple[list[str], list[str]]:
    """Keep each named component's mode without borrowing another's cues."""
    compact = re.sub(r"\s+", "", name)
    # Anatomical subtypes in parentheses are not actions.  Separate numbered
    # procedures so "肺动脉瓣下型)2.PFO修补" cannot become a valve repair.
    procedure_text = re.sub(r"[（(][^()（）]*[)）]", "", compact)
    phrases = re.split(r"\d+[.．、]|[、,，;；+]", procedure_text)
    modes: set[str] = set()
    categories: set[str] = set()
    for phrase in phrases:
        matched = {category for category, pattern in COMPILED_CATEGORIES if pattern.search(phrase)}
        categories.update(matched)
        if matched - {"noncardiac_procedure"}:
            modes.add("cardiac_catheter_intervention" if re.search(
                r"经导管|经皮|封堵|球囊|消融|支架", phrase
            ) else "cardiac_surgery")
        if "noncardiac_procedure" in matched:
            modes.add("noncardiac_surgery")
    if not categories:
        return ["unclassified_operation"], ["unclassified_operation"]
    return sorted(modes), [category for category, _ in COMPILED_CATEGORIES if category in categories]


def procedure_profile(name: str) -> tuple[str, list[str]]:
    """Retain the scalar interface; a heterogeneous field is explicitly mixed."""
    modes, categories = procedure_modes_and_categories(name)
    return modes[0] if len(modes) == 1 else "mixed", categories


def _assertion_text(row: dict) -> str:
    start = int(row.get("assertion_char_start", row.get("char_start", 0))) - int(row.get("char_start", 0))
    end = int(row.get("assertion_char_end", row.get("char_end", 0))) - int(row.get("char_start", 0))
    return row.get("evidence_text", "")[start:end]


def management_context(evidence: list[dict], events: list[dict], management: str) -> dict:
    """Build patient strata and explicitly linked procedure-level observations.

    A repair on a different date cannot establish what happened during another
    operation.  Cross-section handling is linked only within the same document
    and exact operation day.  A copied imaging label stays a separate, weaker
    patient-level flag when it cannot be safely tied to an operation.
    """
    operations = []
    for row in evidence:
        if row["assertion"] == "unrelated_completed":
            operations.append(row)
        elif row["assertion"] == "completed" and row["section_subtype"] == "surgery_record":
            _, categories = procedure_profile(row.get("procedure_name_raw", ""))
            # Pulmonary artery plasty may itself be adjunctive AAOCA treatment.
            # Do not invent a competing lesion from that action alone.
            if set(categories) - {"unclassified_operation", "outflow_or_pulmonary_artery_procedure"}:
                operations.append(row)
    diagnostics = [row for row in evidence if row["assertion"] == "diagnostic_completed"]
    conservative = [row for row in evidence if row["assertion"] == "conservative"]
    intended = [row for row in evidence if row["assertion"] in {"intended", "cancelled_or_declined"}
                and row["event_kind"] != "diagnostic_procedure"]
    contexts, flags, reasons = [], [], []
    evidence_ids: set[str] = set()
    high_priority = False

    def flag(name: str, rows: list[dict], *, review: bool = False, high: bool = False) -> None:
        nonlocal high_priority
        if name not in flags:
            flags.append(name)
        evidence_ids.update(row["evidence_id"] for row in rows)
        if review and name not in reasons:
            reasons.append(name)
        high_priority |= high

    for operation in operations:
        operation_modes, categories = procedure_modes_and_categories(operation.get("procedure_name_raw", ""))
        mode = operation_modes[0] if len(operation_modes) == 1 else "mixed"
        cardiac = any(value.startswith("cardiac_") for value in operation_modes)
        peers = [row for row in evidence if row["section_id"] == operation["section_id"] or (
            row["document_id"] == operation["document_id"]
            and row.get("date_precision") == operation.get("date_precision") == "day"
            and row.get("evidence_date") == operation.get("evidence_date")
            and row.get("section_subtype") in {"surgery_record", "postop_progress"}
        )]
        repairs = [row for row in peers if row["assertion"] == "completed" and _true(row["counts_as_aaoca_surgery"])]
        untreated = [row for row in peers if row["assertion"] == "conservative" and row["strength"] == "high"
                     and re.search(r"未(?:予)?处理|不予处理|无需.{0,4}处理", _assertion_text(row))]
        manipulation = [row for row in peers if row["rule_id"] == "coronary_manipulation_during_other_operation"]
        assessment = [row for row in peers if row["rule_id"] == "coronary_anatomy_during_other_operation"]
        if not cardiac:
            handling, support = "not_applicable", []
        elif repairs and untreated:
            handling, support = "conflicting_documentation", [*repairs, *untreated]
            flag("conflicting_coronary_handling", [operation, *support], review=True, high=True)
        elif repairs:
            handling, support = "concomitant_aaoca_repair", repairs
        elif untreated:
            assessed = any(re.search(r"未见.{0,4}异常|无明显异常", _assertion_text(row)) for row in untreated)
            handling = "assessed_no_intervention" if assessed else "explicitly_not_treated"
            support = untreated
        elif manipulation:
            handling, support = "coronary_manipulated_target_unclear", manipulation
        elif assessment:
            handling, support = "anatomy_documented_intervention_unclear", assessment
        else:
            handling, support = "not_documented", []
        contexts.append({
            "procedure_evidence_id": operation["evidence_id"],
            "procedure_date": operation.get("evidence_date", ""),
            "procedure_mode": mode,
            "procedure_modes": operation_modes,
            "procedure_categories": categories,
            "aaoca_handling": handling,
            "handling_evidence_ids": sorted({row["evidence_id"] for row in support}),
        })
        evidence_ids.update(row["evidence_id"] for row in [operation, *support])
        if cardiac:
            flag("completed_other_cardiac_procedure", [operation])
            if management == "unknown":
                flag("aaoca_management_unresolved_after_other_cardiac_procedure", [operation], review=True, high=True)
            if handling == "not_documented":
                flag("aaoca_handling_not_documented_during_other_procedure", [operation], review=True)
            if handling in {"explicitly_not_treated", "assessed_no_intervention"}:
                flag("aaoca_not_treated_during_other_procedure", support)
            if handling == "anatomy_documented_intervention_unclear":
                flag("coronary_anatomy_seen_intervention_unresolved", support, review=True)
            if (set(categories) & COMPLEX_RELATION_CATEGORIES or manipulation
                    or re.search(r"肺动脉干.{0,4}(?:移位|转位)", operation["procedure_name_raw"])) and not repairs:
                flag("complex_procedure_aaoca_relation_uncertain", [operation, *manipulation], review=True, high=True)
        if "noncardiac_surgery" in operation_modes:
            flag("completed_noncardiac_procedure", [operation])
        if mode == "unclassified_operation":
            flag("completed_procedure_type_unclassified", [operation], review=True, high=True)

    modes = sorted({mode for context in contexts for mode in context["procedure_modes"]})
    categories = sorted({category for context in contexts for category in context["procedure_categories"]})
    handling_values = sorted({context["aaoca_handling"] for context in contexts
                             if any(mode.startswith("cardiac_") for mode in context["procedure_modes"])})
    cardiac_status = ("completed_other_cardiac_procedure" if any(mode.startswith("cardiac_") for mode in modes)
                      else "diagnostic_only_documented" if diagnostics else "none_documented")
    if diagnostics and not events and not operations:
        flag("diagnostic_procedure_without_therapeutic_operation", diagnostics, review=management == "unknown")
    if intended and conservative and not events:
        flag("mixed_management_stages", [*intended, *conservative], review=True)
    if management == "intended_surgery":
        flag("aaoca_surgical_intent_completion_unproven", intended, review=True)
    declined = [row for row in intended if row["assertion"] == "cancelled_or_declined"
                or row["rule_id"] == "aaoca_surgery_recommended_family_deferred"]
    if declined:
        flag("surgery_cancelled_declined_or_deferred", declined, review=not events)
    for row in evidence:
        row_flags = _list(row.get("flags"))
        if "embedded_imaging_nonoperation_label" in row_flags:
            flag("nonoperation_reported_in_imaging_only", [row], review=True)
        if row["rule_id"] == "aaoca_management_decision_pending":
            flag("management_decision_pending_documented", [row], review=management == "unknown")
    if len(events) > 1:
        flag("multiple_aaoca_surgery_events", [row for row in evidence if row["evidence_id"] in
             {event["primary_evidence_id"] for event in events}], review=True)
    if any(event["date_status"] != "known" for event in events):
        flag("aaoca_surgery_date_uncertain", [row for row in evidence if row["evidence_id"] in
             {event["primary_evidence_id"] for event in events}], review=True)
    if management == "unknown" and not reasons:
        flag("insufficient_management_documentation", [], review=True)
    return {
        "other_cardiac_procedure_status": cardiac_status,
        "other_procedure_modes": modes,
        "other_procedure_categories": categories,
        "aaoca_handling_during_other_procedure": handling_values[0] if len(handling_values) == 1 else
            "multiple_contexts" if handling_values else "not_applicable",
        "other_procedure_contexts": contexts,
        "management_complexity_flags": flags,
        "management_context_evidence_ids": sorted(evidence_ids),
        "complex_case_review_priority": "high" if high_priority else "medium" if reasons else "routine",
        "complex_case_review_reasons": reasons,
    }
