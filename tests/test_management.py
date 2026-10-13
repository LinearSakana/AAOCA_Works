from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from aaoca_pipeline.io_utils import sha256_file, write_csv, write_json
from aaoca_pipeline.management import (
    DeterministicManagementEvidenceExtractor,
    resolve_aaoca_cohort,
    validate_management_package,
    write_management_package,
)


def _section(
    patient_id: str,
    section_id: str,
    text: str,
    *,
    day: str = "2024-05-02",
    section_type: str = "progress",
    subtype: str = "",
) -> dict:
    document_id = section_id.split("_s", 1)[0]
    return {
        "patient_id": patient_id,
        "document_id": document_id,
        "section_id": section_id,
        "source_pdf": f"restricted/{document_id}.pdf",
        "section_type": section_type,
        "section_subtype": subtype,
        "section_date": day,
        "page_start": 1,
        "page_end": 1,
        "text_source": "pdf_text_layer",
        "date_requires_review": False,
        "parse_status": "ok",
        "text": text,
        "text_path": f"sections/{document_id}.json",
        "text_reference": "/sections/0/text",
    }


class ManagementTests(unittest.TestCase):
    def _make_sources(self, root: Path) -> tuple[Path, Path]:
        run = root / "run"
        review = root / "aaoca_review"
        sections = [
            _section(
                "p_surgery",
                "doc_surgery_s0001",
                "手术记录\n手术时间：2024-05-02 08:30--11:00\n术前诊断：AAOCA\n"
                "手术名称：1.冠状动脉修补术2.肺动脉补片扩大成形术\n手术经过：术顺。",
                section_type="procedure",
                subtype="surgery_record",
            ),
            _section(
                "p_surgery",
                "doc_surgery_s0002",
                "术后首次病程录。患儿因AAOCA已行冠状动脉修补术，现术后第1天。",
                day="2024-05-03",
                section_type="progress",
                subtype="postop_progress",
            ),
            _section(
                "p_history",
                "doc_history_s0001",
                "既往史：2020-01-02于外院行冠脉异常起源纠治术，术后恢复可。",
                day="2024-06-01",
                section_type="admission",
            ),
            _section(
                "p_intent",
                "doc_intent_s0001",
                "术前讨论：诊断AAOCA。拟施手术名称和方式：1.冠状动脉修补术 "
                "拟施麻醉方式：全身麻醉。",
                section_type="procedure",
                subtype="preoperative_discussion",
            ),
            _section(
                "p_diagnostic",
                "doc_diagnostic_s0001",
                "手术记录。术前诊断：冠状动脉起源异常。手术名称：多根导管冠状动脉造影 "
                "手术医生：测试。手术经过：造影完成。",
                section_type="procedure",
                subtype="surgery_record",
            ),
            _section(
                "p_followup",
                "doc_followup_s0001",
                "右冠状动脉起源于左冠窦，运动试验正常。会诊意见：心内科门诊随访。",
                section_type="consultation",
            ),
            _section(
                "p_untreated",
                "doc_untreated_s0001",
                "手术记录。手术名称：ASD补片修补 手术医生：测试。术中见右冠起源于左冠窦，"
                "术前家属已沟通，本次未予处理。",
                section_type="procedure",
                subtype="surgery_record",
            ),
            _section(
                "p_cancelled",
                "doc_cancelled_s0001",
                "诊断AAOCA，原计划外科手术治疗，家属拒绝手术，暂予出院。",
                section_type="discharge",
            ),
            _section(
                "p_multi",
                "doc_multi_a_s0001",
                "手术记录。手术时间：2022-03-01。手术名称：冠脉异常起源纠治术 手术医生：测试。",
                day="2022-03-01",
                section_type="procedure",
                subtype="surgery_record",
            ),
            _section(
                "p_multi",
                "doc_multi_b_s0001",
                "手术记录。手术时间：2023-04-02。手术名称：冠状动脉开口成形术 手术医生：测试。",
                day="2023-04-02",
                section_type="procedure",
                subtype="surgery_record",
            ),
            _section(
                "p_declined_multidisciplinary",
                "doc_declined_s0001",
                "出院诊断：冠状动脉起源异常，左冠脉起源于右冠窦。经内外科讨论，"
                "患儿病情危重，考虑手术风险极大，经反复告知家属后，家属决定自动出院，拒绝手术。",
                section_type="discharge",
            ),
            _section(
                "p_discussion_observe",
                "doc_observe_s0001",
                "右冠状动脉起源于左冠窦伴心肌缺血可能需手术治疗。冠脉造影示左右冠脉未见明显受压。"
                "后进行心脏内外科讨论，"
                "讨论结束后胸外科医生与家属沟通，家属要求先出院观察，心血管内科门诊随访，定期复查。",
                section_type="discharge",
            ),
            _section(
                "p_discussion_pending",
                "doc_pending_s0001",
                "右冠状动脉起源于左冠窦。今日完成心导管检查，待结果回报后心脏内外科讨论进一步诊疗计划。"
                "患儿一般情况可，予出院，普通门诊随访。",
                section_type="discharge",
            ),
            _section(
                "p_recommended_deferred",
                "doc_recommended_s0001",
                "出院诊断：冠状动脉起源异常。患儿心内外科讨论建议手术，家属表示再考虑，"
                "办理出院，心外科门诊随访。",
                section_type="discharge",
            ),
            _section(
                "p_other_untreated",
                "doc_other_untreated_s0001",
                "手术记录。术中诊断：房间隔缺损、冠状动脉畸形。手术名称：ASD修补术。"
                "术中探查见冠状动脉开口未见明显异常，未处理。术顺。",
                section_type="procedure",
                subtype="surgery_record",
            ),
            _section(
                "p_other_only",
                "doc_other_only_s0001",
                "手术记录。术前诊断：VSD/PFO/单支左冠。手术名称：1.VSD修补2.PFO修补。"
                "术后食道超声无残余分流，术顺。",
                section_type="procedure",
                subtype="surgery_record",
            ),
            _section(
                "p_other_lesion_refusal",
                "doc_other_refusal_s0001",
                "诊断包括右冠状动脉起源于左冠窦。患儿主动脉瓣重度狭窄，心胸外科考虑急诊手术，"
                "告知风险后家长拒绝手术，自动出院。",
                section_type="discharge",
            ),
            _section(
                "p_declined_with_followup",
                "doc_declined_followup_s0001",
                "出院诊断：右冠状动脉起源于左冠窦。经心脏内外科讨论，考虑手术风险，"
                "家属拒绝手术并要求自动出院，嘱心内科门诊随访观察。",
                section_type="discharge",
            ),
            _section(
                "p_same_day_later_intent",
                "doc_same_day_s0001",
                "右冠状动脉起源于左冠窦。经心脏内外科讨论后决定先门诊随访观察。",
                section_type="progress",
            ),
            _section(
                "p_same_day_later_intent",
                "doc_same_day_s0002",
                "右冠状动脉起源于左冠窦。心脏内外科讨论建议手术，家属表示再考虑并办理出院。",
                section_type="discharge",
            ),
        ]
        patient_ids = [
            "p_surgery",
            "p_history",
            "p_intent",
            "p_diagnostic",
            "p_followup",
            "p_untreated",
            "p_cancelled",
            "p_multi",
            "p_declined_multidisciplinary",
            "p_discussion_observe",
            "p_discussion_pending",
            "p_recommended_deferred",
            "p_other_untreated",
            "p_other_only",
            "p_other_lesion_refusal",
            "p_declined_with_followup",
            "p_same_day_later_intent",
            "p_excluded",
        ]
        write_json(run / "run_metadata.json", {"status": "complete"})
        write_csv(
            run / "patient_manifest.csv",
            [{"patient_id": patient_id, "n_pdf": 0 if patient_id == "p_excluded" else 1} for patient_id in patient_ids],
        )
        write_csv(run / "section_index.csv", sections)
        by_document: dict[str, list[dict]] = {}
        for section in sections:
            by_document.setdefault(section["document_id"], []).append(section)
        for document_id, values in by_document.items():
            write_json(run / "sections" / f"{document_id}.json", {"sections": values})

        write_csv(
            review / "exception_cases.csv",
            [
                {
                    "patient_id": "p_excluded",
                    "automatic_aaoca_judgment": "uncertain",
                    "review_status": "not_reviewed",
                    "final_aaoca_judgment": "",
                }
            ],
        )
        write_json(
            review / "run_metadata.json",
            {
                "human_deliverable_scope": "exception_patients_only",
                "exception_patients": 1,
                "nonexception_patients": 17,
                "source_run_metadata_sha256": sha256_file(run / "run_metadata.json"),
                "source_patient_manifest_sha256": sha256_file(run / "patient_manifest.csv"),
                "source_section_index_sha256": sha256_file(run / "section_index.csv"),
            },
        )
        return run, review

    def test_assertion_states_remain_distinct(self):
        extractor = DeterministicManagementEvidenceExtractor()
        planned = _section(
            "p",
            "doc_a_s0001",
            "术前讨论，诊断AAOCA，拟施手术名称和方式：冠状动脉修补术 拟施麻醉方式：全麻。",
            section_type="procedure",
            subtype="preoperative_discussion",
        )
        completed = _section(
            "p",
            "doc_b_s0001",
            "手术记录，手术时间：2024-05-02，手术名称：冠状动脉修补术 手术医生：测试。",
            section_type="procedure",
            subtype="surgery_record",
        )
        diagnostic = _section(
            "p",
            "doc_c_s0001",
            "手术记录，手术名称：多根导管冠状动脉造影 手术医生：测试。",
            section_type="procedure",
            subtype="surgery_record",
        )
        self.assertIn("intended", {row["assertion"] for row in extractor.extract(planned)})
        self.assertIn("completed", {row["assertion"] for row in extractor.extract(completed)})
        diagnostic_rows = extractor.extract(diagnostic)
        self.assertIn("diagnostic_completed", {row["assertion"] for row in diagnostic_rows})
        self.assertFalse(any(row["counts_as_aaoca_surgery"] for row in diagnostic_rows))
        consent = _section(
            "p",
            "doc_d_s0001",
            "心胸外科手术知情同意书。拟定手术日期：2024-05-03。术前诊断：AAOCA。"
            "拟定手术方式：冠状动脉修补术。",
            section_type="administrative",
            subtype="treatment_procedure_consent",
        )
        consent_rows = extractor.extract(consent)
        self.assertIn("intended", {row["assertion"] for row in consent_rows})
        self.assertNotIn("completed", {row["assertion"] for row in consent_rows})
        contraindication = _section(
            "p",
            "doc_e_s0001",
            "冠状动脉起源异常，诊断明确，无手术禁忌症。【手术指征】具备。",
            section_type="procedure",
            subtype="preoperative_discussion",
        )
        self.assertNotIn("conservative", {row["assertion"] for row in extractor.extract(contraindication)})
        no_indication = _section(
            "p",
            "doc_f_s0001",
            "冠状动脉起源异常，目前无手术指征，建议心内科门诊随访。",
            section_type="consultation",
        )
        self.assertIn("conservative", {row["assertion"] for row in extractor.extract(no_indication)})

        untreated = _section(
            "p",
            "doc_g_s0001",
            "VSD术后，右冠状动脉起源于左冠窦未处理。",
            section_type="discharge",
        )
        self.assertIn("conservative", {row["assertion"] for row in extractor.extract(untreated)})

        specific_intent = _section(
            "p",
            "doc_h_s0001",
            "右冠状动脉起源于左冠窦伴心肌缺血，后续可能需外科手术纠治。",
            section_type="consultation",
        )
        intent_rows = extractor.extract(specific_intent)
        self.assertIn("intended", {row["assertion"] for row in intent_rows})
        self.assertFalse(any(row["counts_as_aaoca_surgery"] for row in intent_rows))

        unrelated_plan = _section(
            "p",
            "doc_i_s0001",
            "诊断：室间隔缺损、右冠状动脉起源于左冠窦。拟行VSD修补术。",
            section_type="procedure",
            subtype="preoperative_discussion",
        )
        self.assertNotIn("intended", {row["assertion"] for row in extractor.extract(unrelated_plan)})

        multidisciplinary_decline = _section(
            "p",
            "doc_m_s0001",
            "出院诊断：冠状动脉起源异常。经内外科讨论，考虑手术风险极大，"
            "经反复告知家属后，家属决定自动出院，拒绝手术。",
            section_type="discharge",
        )
        decline_rows = extractor.extract(multidisciplinary_decline)
        self.assertIn(
            "aaoca_multidisciplinary_surgery_declined",
            {row["rule_id"] for row in decline_rows},
        )
        self.assertNotIn("completed", {row["assertion"] for row in decline_rows})
        self.assertTrue(all(row["evidence_date"] == "2024-05-02" for row in decline_rows))

        observation_after_discussion = _section(
            "p",
            "doc_n_s0001",
            "右冠状动脉起源于左冠窦伴心肌缺血可能需手术治疗。造影示左右冠脉未见明显受压。"
            "后进行心脏内外科讨论，"
            "讨论结束后胸外科医生与家属沟通，家属要求先出院观察，心血管内科门诊随访，定期复查。",
            section_type="discharge",
        )
        observation_rows = extractor.extract(observation_after_discussion)
        self.assertIn(
            "aaoca_multidisciplinary_observation",
            {row["rule_id"] for row in observation_rows},
        )

        unrelated_refusal = _section(
            "p",
            "doc_o_s0001",
            "诊断包括右冠状动脉起源于左冠窦。患儿主动脉瓣重度狭窄，"
            "心胸外科考虑急诊手术，告知风险后家长拒绝手术。",
            section_type="discharge",
        )
        self.assertNotIn(
            "aaoca_multidisciplinary_surgery_declined",
            {row["rule_id"] for row in extractor.extract(unrelated_refusal)},
        )

        diagnostic_discharge_template = _section(
            "p",
            "doc_p_s0001",
            "冠状动脉起源异常待查，患儿拟择期手术造影检查，术后一般情况可办理出院。",
            section_type="progress",
        )
        self.assertNotIn(
            "aaoca_planned_surgery_discharge_before_completion",
            {row["rule_id"] for row in extractor.extract(diagnostic_discharge_template)},
        )

        imaging_followup_template = _section(
            "p",
            "doc_q_s0001",
            "冠状动脉造影报告：右冠起源异常，近段偏细，请结合CT，建议随访。"
            "病程与治疗经过：已完成造影，术顺，予出院。",
            section_type="discharge",
        )
        self.assertNotIn(
            "aaoca_followup_observation",
            {row["rule_id"] for row in extractor.extract(imaging_followup_template)},
        )

        embedded_imaging_untreated = _section(
            "p",
            "doc_r_s0001",
            "经食管超声心动图：VSD/右冠状动脉起源左冠窦(未处理)/PH术后，无残余分流。",
            section_type="discharge",
        )
        embedded_rows = [
            row
            for row in extractor.extract(embedded_imaging_untreated)
            if row["rule_id"] == "aaoca_explicit_nonoperative_plan"
        ]
        self.assertTrue(embedded_rows)
        self.assertTrue(all(row["strength"] == "medium" for row in embedded_rows))
        self.assertTrue(all("embedded_imaging_nonoperation_label" in row["flags"] for row in embedded_rows))
        self.assertTrue(
            all(
                row["char_start"] <= row["assertion_char_start"] < row["assertion_char_end"] <= row["char_end"]
                for row in embedded_rows
            )
        )

        electrophysiology_risk_plan = _section(
            "p",
            "doc_j_s0001",
            "射频消融术前讨论：警惕冠状动脉痉挛，必要时及时开通冠脉进行血运重建。",
            section_type="procedure",
            subtype="preoperative_discussion",
        )
        self.assertFalse(
            any(row["event_kind"] == "aaoca_surgery" for row in extractor.extract(electrophysiology_risk_plan))
        )

        nonstandard_history = _section(
            "p",
            "doc_k_s0001",
            "既往史：右冠状动脉起源于左冠窦，2023-08于外院行右冠状动脉开口高位手术，术后随访。",
            section_type="admission",
        )
        history_rows = extractor.extract(nonstandard_history)
        self.assertIn("completed", {row["assertion"] for row in history_rows})
        self.assertTrue(any(row["counts_as_aaoca_surgery"] for row in history_rows))

        month_only_history = _section(
            "p",
            "doc_l_s0001",
            "右冠状动脉起源于左冠窦，2023.08于外院行右冠状动脉开口高位手术，术后随访。",
            section_type="admission",
        )
        month_rows = [row for row in extractor.extract(month_only_history) if row["assertion"] == "completed"]
        self.assertTrue(month_rows)
        self.assertEqual(month_rows[0]["evidence_date"], "2023-08")
        self.assertEqual(month_rows[0]["date_precision"], "month")
        self.assertEqual(month_rows[0]["date_status"], "partial")

    def test_realistic_package_statuses_and_event_deduplication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review = self._make_sources(root)
            output = root / "management"
            result = write_management_package(run, review, output)
            self.assertEqual(result["validation"]["validation_status"], "passed")
            with (output / "management_summary.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = {row["patient_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(len(rows), 17)
            self.assertNotIn("p_excluded", rows)
            self.assertEqual(rows["p_surgery"]["observed_management"], "surgery")
            self.assertEqual(rows["p_surgery"]["n_surgery_events"], "1")
            self.assertEqual(rows["p_history"]["observed_management"], "surgery")
            self.assertEqual(rows["p_history"]["first_surgery_date"], "2020-01-02")
            self.assertEqual(rows["p_intent"]["observed_management"], "intended_surgery")
            self.assertEqual(rows["p_diagnostic"]["observed_management"], "unknown")
            self.assertEqual(rows["p_followup"]["observed_management"], "conservative")
            self.assertEqual(rows["p_untreated"]["observed_management"], "conservative")
            self.assertEqual(rows["p_untreated"]["has_unrelated_surgery_evidence"], "True")
            self.assertEqual(rows["p_cancelled"]["observed_management"], "intended_surgery")
            self.assertEqual(rows["p_multi"]["n_surgery_events"], "2")
            self.assertEqual(rows["p_declined_multidisciplinary"]["observed_management"], "intended_surgery")
            self.assertEqual(rows["p_discussion_observe"]["observed_management"], "conservative")
            self.assertEqual(rows["p_discussion_observe"]["actual_aaoca_surgery"], "unknown")
            self.assertEqual(rows["p_discussion_pending"]["observed_management"], "unknown")
            self.assertEqual(rows["p_recommended_deferred"]["observed_management"], "intended_surgery")
            self.assertEqual(rows["p_other_untreated"]["observed_management"], "conservative")
            self.assertEqual(rows["p_other_untreated"]["actual_aaoca_surgery"], "no")
            self.assertEqual(rows["p_other_only"]["observed_management"], "unknown")
            self.assertEqual(rows["p_other_only"]["overall_treatment_status"], "surgery")
            self.assertEqual(
                rows["p_other_only"]["overall_treatment_rule"],
                "completed_non_aaoca_surgery_evidence",
            )
            self.assertEqual(rows["p_other_only"]["has_unrelated_surgery_evidence"], "True")
            self.assertEqual(rows["p_other_only"]["n_unrelated_surgery_evidence_rows"], "1")
            self.assertIn("VSD", " ".join(json.loads(rows["p_other_only"]["unrelated_procedure_names"])))
            self.assertTrue(rows["p_other_only"]["primary_evidence_id"])
            self.assertIn(
                "unrelated_completed_operation_not_aaoca_management",
                json.loads(rows["p_other_only"]["review_reasons"]),
            )
            self.assertEqual(rows["p_other_lesion_refusal"]["observed_management"], "unknown")
            self.assertEqual(rows["p_declined_with_followup"]["observed_management"], "intended_surgery")
            self.assertEqual(rows["p_same_day_later_intent"]["observed_management"], "intended_surgery")
            with (output / "qc" / "review_queue.csv").open(encoding="utf-8-sig", newline="") as handle:
                qc_rows = list(csv.DictReader(handle))
            other_only_issues = {
                row["issue_type"] for row in qc_rows if row["patient_id"] == "p_other_only"
            }
            self.assertIn("unrelated_operation_without_aaoca_management", other_only_issues)

    def test_completed_human_relevance_label_overrides_automatic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review = self._make_sources(root)
            cases = _read(review / "exception_cases.csv")
            cases[0].update(review_status="reviewed", final_aaoca_judgment="yes")
            write_csv(review / "exception_cases.csv", cases)
            selection, receipt = resolve_aaoca_cohort(run, review)
            selected = {row["patient_id"] for row in selection if row["included_for_management"]}
            self.assertIn("p_excluded", selected)
            self.assertEqual(receipt["included_patients"], 18)

    def test_validator_detects_evidence_span_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review = self._make_sources(root)
            output = root / "management"
            write_management_package(run, review, output)
            rows = _read(output / "management_evidence.csv")
            rows[0]["evidence_text"] += "tampered"
            write_csv(output / "management_evidence.csv", rows)
            result = validate_management_package(output, run, review)
            self.assertEqual(result["validation_status"], "failed")
            self.assertIn("evidence_span_mismatch", {error["code"] for error in result["errors"]})

    def test_validator_rejects_unsupported_actual_no(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review = self._make_sources(root)
            output = root / "management"
            write_management_package(run, review, output)
            rows = _read(output / "management_summary.csv")
            diagnostic = next(row for row in rows if row["patient_id"] == "p_diagnostic")
            diagnostic["actual_aaoca_surgery"] = "no"
            write_csv(output / "management_summary.csv", rows)
            result = validate_management_package(output, run, review)
            self.assertEqual(result["validation_status"], "failed")
            self.assertIn(
                "actual_surgery_no_without_high_strength_evidence",
                {error["code"] for error in result["errors"]},
            )


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
