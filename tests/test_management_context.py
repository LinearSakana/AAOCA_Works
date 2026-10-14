from __future__ import annotations

import unittest

from aaoca_pipeline.management import aggregate_management, build_surgery_events, extract_management_evidence
from test_management import _section


def summarize(*sections):
    evidence = extract_management_evidence(sections)
    events = build_surgery_events(evidence)
    rows, _ = aggregate_management(
        [{"patient_id": "p", "included_for_management": True, "judgment_source": "test"}], evidence, events
    )
    return rows[0], evidence


def operation(text, *, day="2024-05-02", section_id="doc_a_s0001"):
    return _section("p", section_id, text, day=day, section_type="procedure", subtype="surgery_record")


class ManagementContextTests(unittest.TestCase):
    def test_overlapping_rules_are_one_assertion_with_all_rule_provenance(self):
        row, evidence = summarize(_section(
            "p", "doc_a_s0001", "AAOCA无需手术干预。", section_type="progress",
        ))
        conservative = [item for item in evidence if item["assertion"] == "conservative"]
        self.assertEqual(len(conservative), 1)
        self.assertEqual(set(conservative[0]["matched_rule_ids"]),
                         {"aaoca_no_near_term_intervention", "aaoca_explicit_nonoperative_plan"})
        self.assertEqual(row["observed_management"], "conservative")
        self.assertEqual(row["actual_aaoca_surgery"], "no")

    def test_same_day_distinct_decisions_keep_separate_offsets(self):
        _, evidence = summarize(_section(
            "p", "doc_a_s0001", "AAOCA无需手术干预。复查后再次讨论：AAOCA无需手术干预。",
            section_type="progress",
        ))
        conservative = [item for item in evidence if item["assertion"] == "conservative"]
        self.assertEqual(len(conservative), 2)
        self.assertNotEqual(conservative[0]["assertion_char_start"], conservative[1]["assertion_char_start"])

    def test_mixed_modes_keep_surgery_catheter_and_noncardiac_components(self):
        row, _ = summarize(operation(
            "手术记录。手术名称：1.VSD修补2.经导管肺动脉瓣植入术3.阑尾切除术 手术医生：测试。术顺。"
        ))
        self.assertEqual(row["other_procedure_modes"],
                         ["cardiac_catheter_intervention", "cardiac_surgery", "noncardiac_surgery"])
        context = row["other_procedure_contexts"][0]
        self.assertEqual(context["procedure_mode"], "mixed")
        self.assertEqual(context["procedure_modes"], row["other_procedure_modes"])
        self.assertIn("completed_other_cardiac_procedure", row["management_complexity_flags"])
        self.assertIn("completed_noncardiac_procedure", row["management_complexity_flags"])
        self.assertEqual(row["actual_aaoca_surgery"], "unknown")

    def test_diagnostic_access_cues_do_not_change_another_component_mode(self):
        row, _ = summarize(operation(
            "手术记录。手术名称：1.经皮冠状动脉造影2.VSD修补 手术医生：测试。术顺。"
        ))
        self.assertEqual(row["other_procedure_modes"], ["cardiac_surgery"])
        self.assertTrue(row["has_diagnostic_procedure_evidence"])

    def test_septal_repair_does_not_resolve_aaoca_management(self):
        row, evidence = summarize(operation(
            "手术记录。手术名称：1.VSD修补2.PFO修补 手术医生：测试。术顺。"
        ))
        self.assertEqual(row["observed_management"], "unknown")
        self.assertEqual(row["overall_treatment_status"], "surgery")
        self.assertEqual(row["actual_aaoca_surgery"], "unknown")
        self.assertEqual(row["other_procedure_categories"], ["septal_defect_repair"])
        self.assertEqual(row["aaoca_handling_during_other_procedure"], "not_documented")
        self.assertEqual(row["complex_case_review_priority"], "high")
        self.assertEqual(row["management_context_evidence_ids"], [evidence[0]["evidence_id"]])

    def test_noncardiac_operation_is_not_a_competing_cardiac_repair(self):
        row, _ = summarize(operation("手术记录。手术名称：腹腔镜下阑尾切除术 手术医生：测试。术顺。"))
        self.assertEqual(row["other_cardiac_procedure_status"], "none_documented")
        self.assertEqual(row["other_procedure_modes"], ["noncardiac_surgery"])
        self.assertEqual(row["aaoca_handling_during_other_procedure"], "not_applicable")
        self.assertNotIn("aaoca_management_unresolved_after_other_cardiac_procedure", row["management_complexity_flags"])

    def test_catheter_therapy_with_angiography_is_not_diagnostic_only(self):
        row, _ = summarize(operation(
            "手术记录。手术名称：1.冠状动脉造影2.房间隔缺损封堵术 手术医生：测试。术顺。"
        ))
        self.assertEqual(row["other_procedure_modes"], ["cardiac_catheter_intervention"])
        self.assertEqual(row["other_cardiac_procedure_status"], "completed_other_cardiac_procedure")
        self.assertTrue(row["has_diagnostic_procedure_evidence"])
        self.assertEqual(row["actual_aaoca_surgery"], "unknown")

    def test_complex_coronary_button_transfer_is_not_automatic_aaoca_repair(self):
        row, evidence = summarize(operation(
            "手术记录。手术名称：1.Switch(ASO)手术2.VSD修补 手术医生：测试。"
            "术中见单支右冠，制取冠状动脉Button，游离充分后移植到新主动脉位置。术顺。"
        ))
        self.assertEqual(row["observed_management"], "unknown")
        self.assertEqual(row["aaoca_handling_during_other_procedure"], "coronary_manipulated_target_unclear")
        self.assertIn("complex_procedure_aaoca_relation_uncertain", row["complex_case_review_reasons"])
        supporting = row["other_procedure_contexts"][0]["handling_evidence_ids"]
        self.assertTrue(supporting)
        self.assertTrue(all(item["assertion"] == "context_only" for item in evidence if item["evidence_id"] in supporting))

    def test_concomitant_repair_and_later_unrelated_operation_stay_distinct(self):
        row, _ = summarize(
            operation("手术记录。手术名称：冠状动脉修补术、VSD修补 手术医生：测试。术顺。"),
            operation("手术记录。手术名称：ASD修补 手术医生：测试。术顺。",
                      day="2025-06-01", section_id="doc_a_s0002"),
        )
        self.assertEqual(row["n_surgery_events"], 1)
        self.assertEqual(row["aaoca_handling_during_other_procedure"], "multiple_contexts")
        self.assertEqual({item["aaoca_handling"] for item in row["other_procedure_contexts"]},
                         {"concomitant_aaoca_repair", "not_documented"})

    def test_intraoperative_assessment_and_imaging_label_have_different_strength(self):
        row, _ = summarize(operation(
            "手术记录。术前诊断：冠状动脉畸形。手术名称：ASD修补 手术医生：测试。"
            "冠状动脉开口未见明显异常，未处理。术顺。"
        ))
        self.assertEqual(row["aaoca_handling_during_other_procedure"], "assessed_no_intervention")
        self.assertEqual(row["actual_aaoca_surgery"], "no")
        row, _ = summarize(
            operation("手术记录。手术名称：VSD修补 手术医生：测试。术顺。"),
            _section("p", "doc_a_s0002", "经食管超声心动图：VSD/右冠状动脉起源左冠窦(未处理)/PH术后。",
                     section_type="discharge", day="2024-05-05"),
        )
        self.assertEqual(row["actual_aaoca_surgery"], "unknown")
        self.assertEqual(row["aaoca_handling_during_other_procedure"], "not_documented")
        self.assertIn("nonoperation_reported_in_imaging_only", row["management_complexity_flags"])

    def test_pending_discussion_is_context_not_treatment_decision(self):
        row, evidence = summarize(_section(
            "p", "doc_pending_s0001", "右冠状动脉起源于左冠窦。待检查结果回报后心脏内外科讨论进一步诊疗计划。",
            section_type="discharge",
        ))
        self.assertEqual(row["observed_management"], "unknown")
        self.assertIn("management_decision_pending_documented", row["management_complexity_flags"])
        self.assertTrue(any(item["assertion"] == "context_only" for item in evidence))

    def test_anatomical_subtype_cannot_cross_into_next_procedure(self):
        row, _ = summarize(operation(
            "手术记录。手术名称：1.VSD修补(肺动脉瓣下型)2.PFO修补 手术医生：测试。术顺。"
        ))
        self.assertEqual(row["other_procedure_categories"], ["septal_defect_repair"])

    def test_remote_final_decision_supersedes_plan_only_with_unambiguous_diagnosis(self):
        plan = _section("p", "doc_a_s0001", "右冠状动脉起源于左冠窦，拟行冠脉异常起源纠治术。",
                        day="2024-05-01", section_type="procedure", subtype="preoperative_discussion")
        for diagnosis, decision, expected in [
            ("冠状动脉起源异常", "暂无后续手术指征，嘱长期随访。", "conservative"),
            ("冠状动脉起源异常、房间隔缺损", "暂无手术指征，嘱长期随访。", "intended_surgery"),
            ("1.冠状动脉起源异常\n2.房间隔缺损", "暂无手术指征，嘱长期随访。", "intended_surgery"),
            ("梗阻性肥厚型心肌病、冠状动脉起源异常", "暂无手术指征，嘱长期随访。", "intended_surgery"),
            ("冠状动脉起源异常", "无手术禁忌症，拟下周手术。", "intended_surgery"),
        ]:
            with self.subTest(diagnosis=diagnosis, decision=decision):
                row, _ = summarize(plan, _section(
                    "p", "doc_a_s0002", f"出院诊断：{diagnosis}\n【入院情况】" + "体格检查正常。" * 90
                    + "\n病程与治疗经过：" + decision, section_type="discharge",
                ))
                self.assertEqual(row["observed_management"], expected)

    def test_wrapped_deferral_and_discharge_preserve_cancelled_evidence(self):
        for text in [
            "出院诊断：冠状动脉起源异常。考虑冠状动脉起源异常，拟\n手术治疗，因手术风险大，家属决\n定暂缓手术，办理出院。",
            "冠状动脉起源异常。患儿拟完善辅助检查后择日手术治疗，但家属因\n个人原因要求出院。",
        ]:
            with self.subTest(text=text):
                row, _ = summarize(_section("p", "doc_a_s0001", text, section_type="discharge"))
                self.assertEqual(row["observed_management"], "intended_surgery")
                self.assertTrue(row["has_cancelled_or_declined_evidence"])
                self.assertEqual(row["complex_case_review_priority"], "medium")
                self.assertEqual(row["actual_aaoca_surgery"], "unknown")

    def test_coronary_exploration_and_pericardial_surgery_are_retained(self):
        row, _ = summarize(operation(
            "手术记录。手术名称：VSD修补、肺动脉干移位术 手术医生：测试。手术经过："
            "切开主动脉，探查左冠瓣窦见2个冠脉开口，缝合关闭主动脉切口。术顺。"
        ))
        self.assertEqual(row["aaoca_handling_during_other_procedure"], "anatomy_documented_intervention_unclear")
        self.assertEqual(row["actual_aaoca_surgery"], "unknown")
        row, _ = summarize(operation(
            "手术记录。手术名称：1.心包引流术2.心包剥脱术 手术医生：测试。术顺。"
        ))
        self.assertEqual(row["other_procedure_categories"], ["pericardial_procedure"])
        self.assertEqual(row["overall_treatment_status"], "surgery")
        self.assertEqual(row["n_surgery_events"], 0)

    def test_prior_valve_implant_is_separate_from_later_diagnostic_cath_and_observation(self):
        row, evidence = summarize(
            operation("手术记录。手术名称：1.经导管肺动脉瓣植入术2.置入一根血管的支架3.单根血管操作 "
                      "操作目的：置入带瓣肺动脉支架。术顺。", day="2022-02-22"),
            operation("手术记录。手术名称：1.多根导管冠状动脉造影2.联合的右心和左心导管置入 "
                      "操作目的：检查。术顺。", day="2026-01-06", section_id="doc_a_s0002"),
            _section("p", "doc_a_s0003", "右冠起源于左冠窦。心脏内外科讨论后，家属要求先出院观察。",
                     day="2026-01-08", section_type="discharge"),
        )
        self.assertEqual(row["observed_management"], "conservative")
        self.assertEqual(row["overall_treatment_status"], "surgery")
        self.assertEqual(row["actual_aaoca_surgery"], "unknown")
        self.assertEqual(row["other_procedure_modes"], ["cardiac_catheter_intervention"])
        self.assertEqual(row["other_procedure_categories"], ["valve_procedure", "vascular_stent_procedure"])
        self.assertEqual([context["procedure_date"] for context in row["other_procedure_contexts"]], ["2022-02-22"])
        self.assertTrue(any(item["assertion"] == "diagnostic_completed" for item in evidence))


if __name__ == "__main__":
    unittest.main()
