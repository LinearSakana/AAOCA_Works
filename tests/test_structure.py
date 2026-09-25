"""Synthetic fixtures only: no patient names, identifiers or copied narrative."""
import unittest

from aaoca_pipeline.structure import segment_document


def pages(*texts):
    return [{"page": i, "text": t, "normalized_text": t, "extraction_status": "ok", "flags": []} for i, t in enumerate(texts, 1)]


class StructureTests(unittest.TestCase):
    def test_birth_admission_and_print_do_not_become_document_date(self):
        result = segment_document(pages("2025/1/1 10:30\n\uf0d0 手术记录\n入院记录\n出生日期:2020-01-01\n入院日期:2024-12-02"), "case.pdf")
        self.assertEqual([s["section_type"] for s in result], ["unknown", "admission"])
        self.assertEqual(result[1]["document_date"], "")

    def test_title_dates_and_cross_page_traceability(self):
        source = pages("导航\n2024-01-02 08:30 日常病程\n正文甲", "正文乙\n2024-01-03 09:15 手术记录\n正文丙")
        result = segment_document(source, "record.pdf", "P1", "D1")
        self.assertEqual(result[1]["document_date"], "2024-01-02")
        self.assertEqual(result[1]["document_timestamp"], "2024-01-02T08:30")
        self.assertEqual(result[1]["page_end"], 2)
        covered = [(span["page"], i) for s in result for span in s["page_spans"] for i in range(span["start_line"], span["end_line"] + 1)]
        expected = [(p["page"], i + 1) for p in source for i in range(len(p["normalized_text"].splitlines()))]
        self.assertEqual(covered, expected)

    def test_lab_multiple_reports_on_one_page(self):
        result = segment_document(pages("申请项目:合成项目甲\n送样时间:2024-01-01 06:00\n检验时间\n合成条目\n2024/1/2 08:00:00\n申请项目:合成项目乙\n检验时间\n2024/1/3 10:00:00"), "lab.pdf")
        self.assertEqual(len(result), 2)
        self.assertEqual([s["document_date"] for s in result], ["2024-01-02", "2024-01-03"])
        self.assertEqual(result[0]["mentioned_dates"][0]["role"], "sample_submission")

    def test_lab_conflicting_dates_are_unknown(self):
        result = segment_document(pages("申请项目:合成项目\n检验时间\n2024/1/2 08:00:00\n2024/1/3 10:00:00"), "lab.pdf")
        self.assertEqual(result[0]["document_date"], "")
        self.assertIn("conflicting_test_dates", result[0]["flags"])

    def test_damaged_page_does_not_inherit_date(self):
        source = pages("2024-01-02 08:30 日常病程\n正文", "2024-01-03 09:30\n1234", "后续正文\n出院记录\n记录时间:2024-01-05 09:00")
        source[1]["extraction_status"] = "text_layer_unusable"
        result = segment_document(source, "record.pdf")
        damaged = [s for s in result if "unusable_text_layer" in s["flags"]]
        self.assertEqual(len(damaged), 1)
        self.assertEqual(damaged[0]["section_type"], "unknown")
        self.assertEqual(damaged[0]["document_date"], "")

    def test_duplicate_heading_does_not_make_duplicate_event(self):
        result = segment_document(pages("手术记录\n姓名:合成样本\n2024-01-02 08:30 手术记录\n正文"), "record.pdf")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["document_date"], "2024-01-02")

    def test_narrative_surgery_mentions_do_not_split(self):
        result = segment_document(pages("入院记录\n记录日期:2024-01-02\n2024-01-01 患者拟手术,待评估。\n辅助检查:2023-12-01"), "record.pdf")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["document_date"], "2024-01-02")

    def test_invalid_date_and_partial_date_not_completed(self):
        result = segment_document(pages("入院记录\n记录日期:2024-02-31\n记录时间:3月2日"), "case.pdf")
        self.assertEqual(result[0]["document_date"], "")

    def test_explicit_record_date_conflict_is_flagged(self):
        result = segment_document(pages("入院记录\n记录日期:2024-01-02\n记录时间:2024-01-03"), "case.pdf")
        self.assertEqual(result[0]["document_date"], "")
        self.assertIn("conflicting_document_dates", result[0]["flags"])

    def test_filename_date_not_applied_to_multiple_sections(self):
        result = segment_document(pages("入院记录\n正文\n出院记录\n正文"), "export-2024-01-02.pdf")
        self.assertTrue(all(not s["document_date"] for s in result))

    def test_empty_page_is_retained(self):
        source = pages("")
        source[0]["extraction_status"] = "empty"
        result = segment_document(source, "empty.pdf")
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]["section_type"], result[0]["section_subtype"]),
                         ("nonclinical", "empty_content"))
        self.assertEqual(result[0]["page_spans"][0]["page"], 1)

    def test_short_daily_records_with_different_dates_are_not_merged(self):
        result = segment_document(pages("2024-01-02 08:30 日常病程\n短正文\n2024-01-03 08:30 日常病程\n短正文"), "record.pdf")
        self.assertEqual(len(result), 2)
        self.assertEqual([s["document_date"] for s in result], ["2024-01-02", "2024-01-03"])

    def test_local_ocr_keeps_original_damage_warning_but_can_segment(self):
        source = pages("2024-01-02 08:30 日常病程\n正文")
        source[0].update(analysis_text_source="local_ocr", ocr_status="ok", extraction_status="partial", flags=["vector_outlined_text_suspected"])
        result = segment_document(source, "record.pdf")
        self.assertEqual(result[0]["section_type"], "progress")
        self.assertEqual(result[0]["document_date"], "2024-01-02")
        self.assertEqual(result[0]["date_source"], "local_ocr:title_timestamp")
        self.assertIn("date_requires_review", result[0]["flags"])
        self.assertIn("ocr_unverified", result[0]["flags"])

    def test_lab_cross_page_print_timestamp_is_not_a_test_date(self):
        source = pages("2025/01/01 09:00\n申请项目:合成项目\n检验时间\n2024/01/02 08:00:00", "2025/01/01 09:00\n2024/01/02 08:00:00")
        for page in source:
            page["removed_lines"] = [{"reason": "browser_or_navigation_url", "raw_line": 3}]
        result = segment_document(source, "lab.pdf")
        lab = next(s for s in result if s["section_type"] == "laboratory")
        self.assertEqual(lab["document_date"], "2024-01-02")
        self.assertTrue(any(m["role"] == "print" for m in lab["mentioned_dates"]))

    def test_lab_date_only_column_has_day_precision(self):
        result = segment_document(pages("申请项目:合成项目\n检验时间\n2024/1/2\n2024/1/2"), "lab.pdf")
        self.assertEqual(result[0]["document_date"], "2024-01-02")
        self.assertEqual(result[0]["date_precision"], "day")
        self.assertEqual(result[0]["document_timestamp"], "")

    def test_conflicting_same_day_record_times_keep_only_day(self):
        result = segment_document(pages("入院记录\n记录日期:2024-01-02 08:00\n记录时间:2024-01-02 15:00"), "record.pdf")
        self.assertEqual(result[0]["document_date"], "2024-01-02")
        self.assertEqual(result[0]["document_timestamp"], "")
        self.assertEqual(result[0]["date_precision"], "day")
        self.assertIn("conflicting_document_times", result[0]["flags"])

    def test_administrative_narrative_is_not_a_title(self):
        result = segment_document(pages("入院记录\n请阅读知情同意书\n已签署知情同意书"), "record.pdf")
        self.assertEqual(len(result), 1)

    def test_unambiguous_ocr_joined_day_hour_is_recognized(self):
        source = pages("入院记录\n记录日期:2024-01-0213:30")
        source[0].update(analysis_text_source="local_ocr", ocr_status="ok", extraction_status="partial")
        result = segment_document(source, "record.pdf")
        self.assertEqual(result[0]["document_timestamp"], "2024-01-02T13:30")
        self.assertIn("date_requires_review", result[0]["flags"])

    def test_ambiguous_compact_day_hour_is_not_guessed(self):
        result = segment_document(pages("入院记录\n记录日期:2024-01-213:30"), "record.pdf")
        self.assertEqual(result[0]["document_date"], "")

    def test_bulleted_lab_applications_remain_independent_reports(self):
        result = segment_document(pages(
            "动脉血 共 2 项\n• 申请项目: 快速CTNI(全血CICU)\n检验项\nHS-CTNI\n"
            "● 申请项目:\n检验项\npH\nPaCO2\nPaO2\nHCO3-\nLac\n"
            "• 申请项目:\n检验项\nNT-proBNP"
        ), "lab.pdf")
        self.assertEqual([s["section_type"] for s in result],
                         ["nonclinical", "laboratory", "laboratory", "laboratory"])
        self.assertEqual([s["section_title"] for s in result[1:]],
                         ["快速CTNI(全血CICU)", "血气分析", "NT-proBNP"])
        self.assertEqual([s["section_subtype"] for s in result[1:]],
                         ["cardiac_biomarker", "blood_gas", "cardiac_biomarker"])

    def test_mixed_lab_panel_does_not_get_a_guessed_title(self):
        result = segment_document(pages(
            "申请项目:\n检验项\npH\nPaCO2\nPaO2\nHCO3-\n血浆肝素含量"
        ), "lab.pdf")
        self.assertEqual(result[0]["section_subtype"], "mixed_panel")
        self.assertEqual(result[0]["section_title"], "")

    def test_structured_outpatient_without_title_starts_after_navigation(self):
        result = segment_document(pages(
            "返回查询页面\n病历文书\n上海儿童医学中心\n"
            "就诊日期:2025-08-05 09:00 姓名:合成样本 门诊号:123 就诊科室:心胸外科\n"
            "主诉:复查\n现病史:无不适\n门诊初步诊断:待复查\n治疗计划:复诊\n"
            "上海儿童医学中心\n"
            "就诊日期:2025-08-06 10:00 姓名:合成样本 门诊号:123 就诊科室:心胸外科\n"
            "主诉:复查\n现病史:无不适\n治疗计划:复诊"
        ), "record.pdf")
        self.assertEqual([s["section_type"] for s in result], ["nonclinical", "outpatient", "outpatient"])
        self.assertEqual([s["document_date"] for s in result[1:]], ["2025-08-05", "2025-08-06"])
        self.assertTrue(all(s["section_title"] == "" for s in result[1:]))
        self.assertTrue(all(s["section_subtype"] == "outpatient_record" for s in result[1:]))

    def test_outpatient_field_mentions_alone_do_not_split_narrative(self):
        result = segment_document(pages(
            "入院记录\n记录日期:2024-01-02\n患者曾在门诊主诉胸痛,现病史另见门诊记录。\n"
            "就诊日期:2024-01-01\n主诉:复查"
        ), "record.pdf")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["section_type"], "admission")

    def test_repeated_outpatient_form_with_partial_plan_has_its_own_date(self):
        result = segment_document(pages(
            "上海儿童医学中心\n就诊日期:2025-08-05 09:00 就诊科室:心胸外科\n"
            "主诉:复查\n现病史:无不适\n治疗计划:随诊\n"
            "上海儿童医学中心\n就诊日期:2025-08-06 10:00 就诊科室:儿内科\n"
            "主诉:复查\n现病史:无不适"
        ), "record.pdf")
        self.assertEqual([s["section_type"] for s in result], ["outpatient", "outpatient"])
        self.assertEqual([s["document_date"] for s in result], ["2025-08-05", "2025-08-06"])

    def test_observed_consultation_and_antibiotic_titles(self):
        result = segment_document(pages(
            "返回查询页面\n院内会诊単\n会诊目的:协助诊治\n会诊意见:随诊\n"
            "2024-10-0617:33调整抗生素记录\n记录医师:合成样本"
        ), "record.pdf")
        self.assertEqual([s["section_type"] for s in result], ["nonclinical", "consultation", "progress"])
        self.assertEqual(result[1]["section_title"], "院内会诊单")
        self.assertEqual(result[2]["section_subtype"], "antibiotic_adjustment")

    def test_observed_promises_are_administrative_boundaries(self):
        result = segment_document(pages(
            "返回查询页面\n(住院患者临时离院风险知情及责任承诺书)\n签名:合成样本\n"
            "防治新型冠状病毒家属入院承诺书\n签名:合成样本"
        ), "record.pdf")
        self.assertEqual([s["section_type"] for s in result],
                         ["nonclinical", "administrative", "administrative"])
        self.assertEqual([s["section_subtype"] for s in result[1:]],
                         ["leave_commitment", "infection_control_commitment"])
        self.assertEqual(result[1]["section_title"], "住院患者临时离院风险知情及责任承诺书")

    def test_progress_subtypes_do_not_change_record_boundaries(self):
        cases = {
            "日常病程录": "daily_progress",
            "张某主任医师查房": "round",
            "张某主任医师首次查房": "first_round",
            "告病重第2天张某主任医师查房": "critical_round",
            "转入记录": "transfer",
            "住院首次病程录": "initial_progress",
            "危重病例讨论记录": "case_discussion",
            "术后首次病程录": "postop_progress",
            "大型检查(CT、MRI、DSA、核素检查等)病程录": "procedure_imaging_progress",
        }
        for title, subtype in cases.items():
            with self.subTest(title=title):
                result = segment_document(pages(f"2024-01-02 08:30 {title}\n正文"), "record.pdf")
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["section_type"], "progress")
                self.assertEqual(result[0]["section_subtype"], subtype)

    def test_administrative_and_procedure_subtypes(self):
        cases = {
            "住院患者生物样本留取知情同意书": ("administrative", "research_consent"),
            "病危/病重通知书": ("administrative", "condition_communication"),
            "入院告知书": ("administrative", "admission_notice"),
            "输血(血液制品)治疗知情同意书": ("administrative", "treatment_procedure_consent"),
            "PICU床旁超声操作记录": ("procedure", "bedside_ultrasound"),
            "有创操作记录": ("procedure", "invasive_procedure"),
            "心导管手术记录": ("procedure", "surgery_record"),
            "术前讨论": ("procedure", "preoperative_discussion"),
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                section = segment_document(pages(f"{title}\n正文"), "record.pdf")[0]
                self.assertEqual((section["section_type"], section["section_subtype"]), expected)


if __name__ == "__main__":
    unittest.main()
