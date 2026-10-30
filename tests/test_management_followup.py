from __future__ import annotations

import unittest

from aaoca_pipeline.management_followup import (
    DEFAULT_RULES,
    aggregate_followup,
    extract_followup_evidence,
    load_rules,
)


def section(
    patient_id: str,
    text: str,
    *,
    section_id: str,
    section_type: str = "progress",
    section_subtype: str = "round",
    section_date: str = "2025-01-01",
    page: int = 1,
) -> dict:
    return {
        "patient_id": patient_id,
        "document_id": f"doc_{patient_id}",
        "section_id": section_id,
        "section_type": section_type,
        "section_subtype": section_subtype,
        "section_title": section_subtype or section_type,
        "section_date": section_date,
        "document_date": section_date,
        "page_start": page,
        "page_end": page,
        "source_pdf": "source.pdf",
        "text_path": f"sections/doc_{patient_id}.json",
        "text_reference": "/sections/0/text",
        "text": text,
    }


def source(patient_id: str) -> dict:
    return {
        "patient_id": patient_id,
        "observed_management": "unknown",
        "actual_aaoca_surgery": "unknown",
        "overall_treatment_status": "unknown",
    }


class ManagementFollowupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = load_rules()

    def classify(self, patient_id: str, sections: list[dict]) -> tuple[dict, list[dict]]:
        evidence = extract_followup_evidence(sections, self.rules)
        summaries, qc = aggregate_followup([source(patient_id)], evidence)
        return summaries[0], qc

    def test_confirmed_hcm_is_temporarily_excluded(self) -> None:
        row, _ = self.classify(
            "p_hcm",
            [
                section(
                    "p_hcm",
                    "出院记录 出院诊断:1.梗阻性肥厚型心肌病 2.冠状动脉起源异常。",
                    section_id="s_hcm",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["complex_heart_disease_status"], "confirmed")
        self.assertEqual(row["decision_path"], "combined_other_complex_heart_disease")
        self.assertEqual(row["study_disposition"], "temporarily_excluded_complex_heart_disease")

    def test_suspected_lqts_is_not_auto_excluded(self) -> None:
        row, _ = self.classify(
            "p_lqts",
            [
                section(
                    "p_lqts",
                    "入院诊断:晕厥待查,窦性静止,长QT综合征待查,冠状动脉起源异常。",
                    section_id="s_lqts",
                    section_type="admission",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["complex_heart_disease_status"], "suspected")
        self.assertEqual(row["study_disposition"], "needs_review_possible_complex_heart_disease")

    def test_severe_aortic_stenosis_is_a_confirmed_complex_exclusion(self) -> None:
        row, _ = self.classify(
            "p_severe_as",
            [
                section(
                    "p_severe_as",
                    "出院诊断:1.危重型主动脉瓣狭窄 2.冠状动脉起源异常。",
                    section_id="s_severe_as",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["complex_heart_disease_status"], "confirmed")
        self.assertEqual(row["decision_path"], "combined_other_complex_heart_disease")

    def test_ruled_out_dorv_and_template_rvot_are_not_confirmed(self) -> None:
        row, _ = self.classify(
            "p_diff",
            [
                section(
                    "p_diff",
                    "鉴别诊断:DORV/PS。根据影像学检查可排除诊断DORV/PS。",
                    section_id="s_diff",
                    section_type="progress",
                    section_subtype="initial_progress",
                ),
                section(
                    "p_diff",
                    "手术同意书 通用风险包括右心室流出道狭窄、残余分流等。",
                    section_id="s_consent",
                    section_type="administrative",
                    section_subtype="treatment_procedure_consent",
                ),
            ],
        )
        self.assertEqual(row["complex_heart_disease_status"], "none")

    def test_locally_negated_aortic_coarctation_is_not_confirmed(self) -> None:
        row, _ = self.classify(
            "p_no_coa",
            [
                section(
                    "p_no_coa",
                    "术后病程记录：升主动脉造影提示左弓，无主动脉缩窄及动脉导管未闭。",
                    section_id="s_no_coa",
                    section_type="progress",
                    section_subtype="postop_progress",
                )
            ],
        )
        self.assertEqual(row["complex_heart_disease_status"], "none")

    def test_later_no_indication_overrides_earlier_plan(self) -> None:
        row, _ = self.classify(
            "p_observe",
            [
                section(
                    "p_observe",
                    "冠状动脉起源异常，拟进一步评估后考虑手术治疗。",
                    section_id="s_plan",
                    section_date="2025-01-01",
                ),
                section(
                    "p_observe",
                    "科内讨论后认为冠状动脉起源异常目前暂无手术指征，继续随访观察。",
                    section_id="s_final",
                    section_type="discharge",
                    section_subtype="",
                    section_date="2025-01-05",
                    page=8,
                ),
            ],
        )
        self.assertEqual(row["surgery_indication"], "no")
        self.assertEqual(row["decision_path"], "clinician_no_indication_conservative")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "conservative_followup")

    def test_diagnostic_catheter_indication_is_not_therapeutic_indication(self) -> None:
        row, _ = self.classify(
            "p_cath",
            [
                section(
                    "p_cath",
                    "患儿存在冠状动脉起源异常，具备心导管检查术及冠状动脉造影手术指征。",
                    section_id="s_cath",
                    section_type="procedure",
                    section_subtype="preoperative_discussion",
                )
            ],
        )
        self.assertEqual(row["surgery_indication"], "unclear")
        self.assertNotIn("surgery_indicated", row["decision_path"])

    def test_recommended_surgery_then_family_declined_preserves_both_axes(self) -> None:
        row, _ = self.classify(
            "p_declined",
            [
                section(
                    "p_declined",
                    "经心外科讨论，冠状动脉起源异常建议手术治疗。家属明确拒绝手术，要求出院。",
                    section_id="s_declined",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["surgery_indication"], "yes")
        self.assertEqual(row["decision_path"], "surgery_indicated_not_done_family_declined")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "no_aaoca_surgery_documented")
        self.assertEqual(row["followup_management"], "intended_surgery_not_completed")

    def test_discharge_diagnosis_links_generic_team_decision_and_family_deferral(self) -> None:
        sections = [
            section(
                "p_deferred",
                "出院诊断:冠状动脉起源异常\n科内专家讨论后建议手术治疗，家长要求寒假手术，告知风险后出院。",
                section_id="s_deferred",
                section_type="discharge",
                section_subtype="",
            )
        ]
        evidence = extract_followup_evidence(sections, self.rules)
        summaries, _ = aggregate_followup([source("p_deferred")], evidence)
        row = summaries[0]
        self.assertEqual(row["surgery_indication"], "yes")
        self.assertEqual(row["decision_path"], "surgery_indicated_not_done_family_deferred")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "no_aaoca_surgery_documented")
        self.assertTrue(
            any("aaoca_linked_by_structured_section_diagnosis" in item.get("flags", []) for item in evidence)
        )

    def test_competing_diagnosis_prevents_section_level_target_link(self) -> None:
        row, _ = self.classify(
            "p_competing",
            [
                section(
                    "p_competing",
                    "出院诊断:1.房间隔缺损 2.冠状动脉起源异常\n科内讨论建议手术治疗，家长要求寒假手术。",
                    section_id="s_competing",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["surgery_indication"], "unclear")

    def test_later_pending_workup_overrides_earlier_generic_followup(self) -> None:
        row, _ = self.classify(
            "p_pending",
            [
                section(
                    "p_pending",
                    "冠状动脉起源异常，建议门诊随访。",
                    section_id="s_followup",
                    section_date="2025-01-01",
                ),
                section(
                    "p_pending",
                    "出院诊断:冠状动脉起源异常\n待科内病例讨论后再制定治疗方案。",
                    section_id="s_pending",
                    section_type="discharge",
                    section_subtype="",
                    section_date="2025-01-05",
                ),
            ],
        )
        self.assertEqual(row["decision_path"], "continued_evaluation_or_pending")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "unknown")

    def test_same_discharge_pending_decision_beats_generic_followup_template(self) -> None:
        row, _ = self.classify(
            "p_same_discharge_pending",
            [
                section(
                    "p_same_discharge_pending",
                    "出院诊断:冠状动脉起源异常\n待内外科病例讨论后再制定治疗方案。\n3.出院随访心内科，若有不适及时就诊。",
                    section_id="s_same_discharge_pending",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "continued_evaluation_or_pending")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "unknown")

    def test_actual_ama_is_not_recast_as_conservative_by_followup_template(self) -> None:
        row, _ = self.classify(
            "p_ama",
            [
                section(
                    "p_ama",
                    "出院诊断:冠状动脉起源异常\n患儿生命体征平稳，家长要求自动出院，予签字离院。\n3.出院随访心内科。",
                    section_id="s_ama",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "left_against_medical_advice_outcome_unclear")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "unknown")

    def test_discharge_plan_to_complete_stress_test_remains_pending(self) -> None:
        row, _ = self.classify(
            "p_outpatient_test",
            [
                section(
                    "p_outpatient_test",
                    "出院诊断:冠状动脉起源异常\n3.出院随访心内科，出院1周后完善运动平板试验，结果回报后复诊。",
                    section_id="s_outpatient_test",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "continued_evaluation_or_pending")

    def test_other_specialty_followup_is_not_aaoca_conservative_management(self) -> None:
        row, _ = self.classify(
            "p_endocrine_followup",
            [
                section(
                    "p_endocrine_followup",
                    "出院诊断:1.冠状动脉起源异常 2.生长发育迟缓\n3.出院随访内分泌遗传代谢科，出院后1周复诊。",
                    section_id="s_endocrine_followup",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "unclear")

    def test_radiology_suggested_followup_is_not_terminal_management(self) -> None:
        row, _ = self.classify(
            "p_imaging_followup",
            [
                section(
                    "p_imaging_followup",
                    "出院诊断:冠状动脉起源异常\n心脏MRI提示左室心肌稍疏松，心内结构结合ECHO，建议随访。",
                    section_id="s_imaging_followup",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "unclear")

    def test_adjacent_no_coronary_ischemia_assessment_supports_followup(self) -> None:
        row, _ = self.classify(
            "p_no_ischemia",
            [
                section(
                    "p_no_ischemia",
                    "出院诊断:冠状动脉起源异常\n目前评估无明显冠脉缺血证据，患儿一般情况可，予出院，\n嘱后续门诊随访。",
                    section_id="s_no_ischemia",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "clinician_conservative_other")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "conservative_followup")

    def test_later_stable_aaoca_outpatient_observation_supersedes_older_ama(self) -> None:
        row, _ = self.classify(
            "p_longitudinal",
            [
                section(
                    "p_longitudinal",
                    "出院诊断:冠状动脉起源异常\n家长要求自动出院，予签字离院。",
                    section_id="s_old_ama",
                    section_type="discharge",
                    section_subtype="",
                    section_date="2022-01-01",
                ),
                section(
                    "p_longitudinal",
                    "现病史:[患儿冠脉起源异常，无胸痛，平素活动耐量正常，无晕厥。]",
                    section_id="s_later_outpatient",
                    section_type="outpatient",
                    section_subtype="outpatient_record",
                    section_date="2025-01-01",
                ),
            ],
        )
        self.assertEqual(row["decision_path"], "clinician_conservative_other")

    def test_generic_neurology_no_treatment_is_not_no_aaoca_indication(self) -> None:
        row, _ = self.classify(
            "p_neuro",
            [
                section(
                    "p_neuro",
                    "出院诊断:冠状动脉起源异常\n请神经内科会诊，脑电图未见异常，暂无需处理，继续观察。",
                    section_id="s_neuro",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertNotEqual(row["surgery_indication"], "no")

    def test_assessing_surgical_indication_is_not_positive_indication(self) -> None:
        row, _ = self.classify(
            "p_assess",
            [
                section(
                    "p_assess",
                    "出院诊断:冠状动脉起源异常\n科内讨论后建议完善心脏MRI检查后评估手术指征。",
                    section_id="s_assess",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["surgery_indication"], "unclear")
        self.assertEqual(row["decision_path"], "continued_evaluation_or_pending")

    def test_specific_aaoca_followup_is_conservative_despite_other_operation(self) -> None:
        row, _ = self.classify(
            "p_other_op",
            [
                section(
                    "p_other_op",
                    "诊断:1.肺动脉瓣狭窄2.右冠状动脉开口于左冠窦。已行肺动脉瓣球囊扩张。患儿右冠状动脉开口于左冠窦，建议随访，注意是否有缺血表现。",
                    section_id="s_other_op",
                    section_type="progress",
                    section_subtype="first_round",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "clinician_conservative_other")

    def test_postoperative_vsd_does_not_block_aaoca_surgical_referral(self) -> None:
        row, _ = self.classify(
            "p_referral",
            [
                section(
                    "p_referral",
                    "出院诊断:1.冠状动脉起源异常2.室间隔缺损修补术后\n出院随访：心胸外科；出院后就诊于心胸外科。",
                    section_id="s_referral",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "referred_no_outcome")

    def test_detailed_surveillance_schedule_is_conservative(self) -> None:
        row, _ = self.classify(
            "p_surveillance",
            [
                section(
                    "p_surveillance",
                    "出院诊断:冠状动脉起源异常\n出院后定期复查心电图、心脏彩超、运动平板试验（每6-12月复查）。",
                    section_id="s_surveillance",
                    section_type="discharge",
                    section_subtype="",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "clinician_conservative_other")

    def test_preoperative_diagnostic_plan_is_not_terminal_pending_evidence(self) -> None:
        row, _ = self.classify(
            "p_diagnostic_plan",
            [
                section(
                    "p_diagnostic_plan",
                    "术前诊断:冠状动脉起源异常。拟定手术方式:多根导管冠状动脉造影。手术适应症:评估冠状动脉起源、结构及血运。",
                    section_id="s_diagnostic_plan",
                    section_type="procedure",
                    section_subtype="preoperative_discussion",
                )
            ],
        )
        self.assertEqual(row["surgery_indication"], "unclear")
        self.assertEqual(row["decision_path"], "unclear")

    def test_named_aaoca_operation_then_later_unhandled_preserves_indication_and_outcome(self) -> None:
        row, _ = self.classify(
            "p_named_operation",
            [
                section(
                    "p_named_operation",
                    "术前诊断:冠状动脉起源异常。拟定手术方式:冠状动脉开口扩大术或冠状动脉移植术。",
                    section_id="s_intent",
                    section_type="administrative",
                    section_subtype="treatment_procedure_consent",
                    section_date="2025-01-01",
                ),
                section(
                    "p_named_operation",
                    "既往疾病史:冠状动脉起源异常未处理。",
                    section_id="s_unhandled",
                    section_type="admission",
                    section_subtype="",
                    section_date="2025-06-01",
                ),
            ],
        )
        self.assertEqual(row["surgery_indication"], "yes")
        self.assertEqual(row["decision_path"], "surgery_indicated_not_done_other")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "no_aaoca_surgery_documented")

    def test_right_coronary_opening_at_left_sinus_followup_is_linked(self) -> None:
        row, _ = self.classify(
            "p_opening",
            [
                section(
                    "p_opening",
                    "患儿右冠状动脉开口于左冠状窦，建议随访，注意是否有缺血表现。",
                    section_id="s_opening",
                    section_type="progress",
                    section_subtype="first_round",
                )
            ],
        )
        self.assertEqual(row["decision_path"], "clinician_conservative_other")

    def test_plan_does_not_become_completed_surgery(self) -> None:
        row, _ = self.classify(
            "p_plan",
            [
                section(
                    "p_plan",
                    "冠状动脉起源异常，计划完善检查后拟行手术治疗。",
                    section_id="s_plan_only",
                    section_type="admission",
                    section_subtype="",
                )
            ],
        )
        self.assertNotEqual(row["observed_aaoca_treatment_outcome"], "aaoca_surgery_completed")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "unknown")

    def test_other_cardiac_operation_without_coronary_handling_stays_unresolved(self) -> None:
        source_row = source("p_other_operation_unknown")
        source_row.update(
            {
                "overall_treatment_status": "surgery",
                "other_cardiac_procedure_status": "completed_other_cardiac_procedure",
                "aaoca_handling_during_other_procedure": "not_documented",
                "unrelated_procedure_names": '["VSD修补"]',
            }
        )
        summaries, _ = aggregate_followup([source_row], [])
        row = summaries[0]
        self.assertEqual(row["decision_path"], "other_cardiac_procedure_aaoca_handling_unresolved")
        self.assertEqual(row["observed_aaoca_treatment_outcome"], "unknown")

    def test_diagnostic_only_record_gets_a_distinct_review_stratum(self) -> None:
        source_row = source("p_diagnostic_only")
        source_row["other_cardiac_procedure_status"] = "diagnostic_only_documented"
        summaries, _ = aggregate_followup([source_row], [])
        self.assertEqual(
            summaries[0]["decision_path"],
            "diagnostic_workup_terminal_decision_unresolved",
        )

    def test_default_rule_groups_are_complete(self) -> None:
        rules = load_rules()
        self.assertEqual(set(rules["phrases"]), set(DEFAULT_RULES["phrases"]))


if __name__ == "__main__":
    unittest.main()
