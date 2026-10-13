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


if __name__ == "__main__":
    unittest.main()
