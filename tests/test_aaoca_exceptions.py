from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from aaoca_pipeline.aaoca_exceptions import (
    DeterministicAaocaEvidenceExtractor,
    assess_patients,
    validate_review_package,
    write_exception_package,
)
from aaoca_pipeline.io_utils import write_csv, write_json


def _section(patient_id: str, section_id: str, text: str, section_type: str = "progress") -> dict:
    document_id = section_id.split("_s", 1)[0]
    return {
        "patient_id": patient_id,
        "document_id": document_id,
        "section_id": section_id,
        "source_pdf": f"restricted/{document_id}.pdf",
        "section_type": section_type,
        "section_subtype": "",
        "section_date": "2024-01-01",
        "page_start": 1,
        "page_end": 1,
        "text_source": "pdf_text_layer",
        "date_requires_review": False,
        "parse_status": "ok",
        "text": text,
        "text_path": f"sections/{document_id}.json",
        "text_reference": "/sections/0/text",
    }


class AaocaExceptionTests(unittest.TestCase):
    def _make_run(self, root: Path) -> None:
        patients = [
            ("p_typical", 1, "ok"),
            ("p_missing", 0, "no_pdf_in_scope"),
            ("p_header", 1, "partial"),
            ("p_tentative", 1, "ok"),
            ("p_conflict", 1, "ok"),
            ("p_pulmonary", 1, "ok"),
            ("p_unrelated", 1, "ok"),
            ("p_excluded", 1, "ok"),
        ]
        manifest = []
        linkage = []
        for index, (patient_id, n_pdf, status) in enumerate(patients, 1):
            manifest.append(
                {
                    "patient_id": patient_id,
                    "n_pdf": n_pdf,
                    "n_sections": 0 if not n_pdf else 1,
                    "parse_status": status,
                }
            )
            linkage.append(
                {
                    "patient_id": patient_id,
                    "inpatient_id": f"I{index:03d}",
                    "outpatient_id": f"O{index:03d}",
                    "name": f"测试患者{index}",
                }
            )

        sections = {
            "doc_typical": [
                _section(
                    "p_typical",
                    "doc_typical_s0001",
                    "诊断：右冠状动脉异常起源于左冠窦，拟完善冠脉 CTA。",
                )
            ],
            "doc_header": [
                _section(
                    "p_header",
                    "doc_header_s0001",
                    "返回查询页面 2024-01-01 冠状动脉起源异常（心胸外科）",
                    "nonclinical",
                )
            ],
            "doc_tentative": [
                _section(
                    "p_tentative",
                    "doc_tentative_s0001",
                    "心超提示冠脉起源异常可能，建议增强 CT 进一步明确。",
                    "consultation",
                )
            ],
            "doc_conflict": [
                _section(
                    "p_conflict",
                    "doc_conflict_s0001",
                    "首次 CTA：右冠状动脉起源于左冠窦。复查报告：右冠状动脉起源于右冠窦。",
                )
            ],
            "doc_pulmonary": [
                _section(
                    "p_pulmonary",
                    "doc_pulmonary_s0001",
                    "鉴别诊断包括 ALCAPA，即左冠状动脉异常起源于肺动脉。",
                )
            ],
            "doc_unrelated": [
                _section(
                    "p_unrelated",
                    "doc_unrelated_s0001",
                    "因肺炎入院。病程中无胸痛、晕厥或心脏相关诊疗。" * 80,
                )
            ],
            "doc_excluded": [
                _section(
                    "p_excluded",
                    "doc_excluded_s0001",
                    "经专科会诊及增强 CT 检查后排除冠状动脉起源异常。",
                )
            ],
        }

        write_json(root / "run_metadata.json", {"status": "complete"})
        write_json(root / "qc" / "cohort_summary.json", {"source_hash_verification": "passed"})
        write_csv(root / "patient_manifest.csv", manifest)
        write_csv(root / "private" / "patient_linkage.csv", linkage)
        write_csv(root / "section_index.csv", [section for values in sections.values() for section in values])
        for document_id, values in sections.items():
            write_json(root / "sections" / f"{document_id}.json", {"sections": values})

    def test_specific_origin_shorthand_and_branch_are_distinct(self):
        extractor = DeterministicAaocaEvidenceExtractor()
        shorthand = _section("p", "doc_a_s0001", "右冠起自左冠，近端壁内走行。")
        explicit_branch = _section("p", "doc_b_s0001", "右冠状动脉异常起源，起自左前降支。")
        _, shorthand_facts = extractor.extract(shorthand)
        _, branch_facts = extractor.extract(explicit_branch)
        self.assertTrue(any(f.origin == "left_sinus" for f in shorthand_facts))
        self.assertTrue(any(f.origin == "left_anterior_descending" for f in branch_facts))

    def test_exception_queue_only_contains_atypical_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            self._make_run(run)
            cases, evidence, summary = assess_patients(run)
            by_id = {row["patient_id"]: row for row in cases}
            self.assertNotIn("p_typical", by_id)
            self.assertEqual(by_id["p_missing"]["automatic_aaoca_judgment"], "uncertain")
            self.assertEqual(by_id["p_header"]["automatic_aaoca_judgment"], "uncertain")
            self.assertIn("tentative_evidence_only", by_id["p_tentative"]["exception_reasons"])
            self.assertIn("conflicting_coronary_origin_descriptions", by_id["p_conflict"]["exception_reasons"])
            self.assertIn("pulmonary_origin_scope_boundary", by_id["p_pulmonary"]["exception_reasons"])
            self.assertEqual(by_id["p_unrelated"]["automatic_aaoca_judgment"], "no")
            # A later exclusion is still an ordinary yes because the diagnostic
            # direction was meaningfully considered; it need not enter review.
            self.assertNotIn("p_excluded", by_id)
            self.assertEqual(summary["automatic_judgments_all_patients"], {"yes": 5, "uncertain": 2, "no": 1})
            self.assertEqual(summary["patients_total"], 8)
            self.assertEqual(
                {row["patient_id"] for row in evidence},
                {"p_header", "p_tentative", "p_conflict", "p_pulmonary"},
            )

    def test_package_validation_and_human_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            output = Path(temp) / "review"
            self._make_run(run)
            receipt = write_exception_package(run, output)
            self.assertEqual(receipt["human_deliverable_scope"], "exception_patients_only")
            result = validate_review_package(output)
            self.assertEqual(result["validation_status"], "passed")

            with (output / "exception_cases.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["final_aaoca_judgment"] = "yes"
            write_csv(output / "exception_cases.csv", rows, list(rows[0]))
            result = validate_review_package(output)
            self.assertEqual(result["validation_status"], "failed")
            self.assertIn("final_judgment_without_reviewed_status", {e["code"] for e in result["errors"]})


if __name__ == "__main__":
    unittest.main()
