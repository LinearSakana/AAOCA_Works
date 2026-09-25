"""Synthetic identity tests: never put real patient data in a test fixture."""
import csv
import tempfile
import unittest
from pathlib import Path

from aaoca_pipeline.matching import load_cohort, match_file, normalize_identifier, scan_and_match


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def cohort(self, rows):
        path = self.root / "patients.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["住院号", "门诊号", "姓名", "病历", "检验"])
            writer.writerows([list(row) + ["1", "0"] for row in rows])
        return load_cohort(path)

    def test_ids_are_stable_under_csv_row_reorder_and_preserve_zeros(self):
        rows = [("001234", "01000001", "测试甲"), ("001235", "01000002", "测试乙")]
        a = self.cohort(rows)["patients"]
        b = self.cohort(rows[::-1])["patients"]
        self.assertEqual(a[0]["patient_id"], b[1]["patient_id"])
        self.assertEqual(a[0]["inpatient_id"], "001234")

    def test_shared_outpatient_id_is_reported_and_inpatient_disambiguates(self):
        cohort = self.cohort([("001234", "01000001", "测试甲"), ("001235", "01000001", "测试乙")])
        self.assertEqual(cohort["issues"][0]["issue_type"], "identifier_conflict")
        matched = match_file(self.root / "测试甲-病历.pdf", cohort["patients"], "/BasicInfo/01000001/001234)")
        self.assertEqual(matched["match_status"], "matched")
        self.assertEqual(matched["patient_id"], cohort["patients"][0]["patient_id"])
        self.assertEqual(len(matched["candidate_patient_ids"]), 2)

    def test_conflicting_filename_and_header_are_never_assigned(self):
        patients = self.cohort([("001234", "01000001", "测试甲"), ("001235", "01000002", "测试乙")])["patients"]
        result = match_file(self.root / "测试甲-病历.pdf", patients, "/EMR/01000002/001235)")
        self.assertEqual(result["match_status"], "ambiguous")
        self.assertEqual(result["patient_id"], "")

    def test_name_typo_can_only_be_recovered_by_exact_header_identifiers(self):
        patients = self.cohort([("001234", "01000001", "测试甲")])["patients"]
        path = self.root / "测试申-病历.pdf"
        self.assertEqual(match_file(path, patients)["match_status"], "unmatched")
        result = match_file(path, patients, "/EMR/01000001/001234)")
        self.assertEqual(result["patient_id"], patients[0]["patient_id"])
        self.assertIn("filename_name_mismatch", [x["issue_type"] for x in result["match_issues"]])

    def test_clinical_body_numbers_do_not_create_a_patient_match(self):
        patients = self.cohort([("001234", "01000001", "测试甲")])["patients"]
        result = match_file(self.root / "unknown.pdf", patients, "检验结果001234 参考范围01000001")
        self.assertEqual(result["match_status"], "unmatched")

    def test_blank_label_cannot_consume_date_or_next_page_identifier(self):
        patients = self.cohort([("001234", "01000001", "测试甲")])["patients"]
        for blank_label in ("住院号\n2019-02-01", "住院号\n001299", "住院号: 2019-02-01"):
            result = match_file(self.root / "测试甲-病历.pdf", patients,
                                "/EMR/01000001/001234)\n" + blank_label)
            self.assertEqual(result["match_status"], "matched")
            self.assertEqual(result["header_identifiers"]["inpatient_id"], ["001234"])

    def test_conflicting_identifier_in_filename_is_not_overridden_by_header(self):
        patients = self.cohort([("001234", "01000001", "测试甲"), ("001235", "01000002", "测试乙")])["patients"]
        result = match_file(self.root / "测试甲-001235-病历.pdf", patients, "/EMR/01000001/001234)")
        self.assertEqual(result["match_status"], "ambiguous")

    def test_unknown_outpatient_difference_flagged_when_inpatient_matches(self):
        patients = self.cohort([("001234", "01000001", "测试甲")])["patients"]
        result = match_file(self.root / "测试甲-病历.pdf", patients, "/EMR/01000009/001234)")
        self.assertEqual(result["match_status"], "matched")
        self.assertTrue(result["identifier_conflict"])
        self.assertEqual(result["match_issues"][0]["field"], "outpatient_id")

    def test_unknown_inpatient_mismatch_does_not_trust_name(self):
        patients = self.cohort([("001234", "01000001", "测试甲")])["patients"]
        result = match_file(self.root / "测试甲-病历.pdf", patients, "/EMR/01000001/001299)")
        self.assertEqual(result["match_status"], "ambiguous")
        self.assertEqual(result["patient_id"], "")

    def test_multiple_header_patients_including_unknown_patient_quarantined(self):
        patients = self.cohort([("001234", "01000001", "测试甲")])["patients"]
        result = match_file(self.root / "测试甲-病历.pdf", patients,
                            "/EMR/01000001/001234) /BasicInfo/01009999/009999)")
        self.assertEqual(result["match_status"], "ambiguous")

    def test_historical_or_truncated_label_is_flagged_without_overriding_url(self):
        patients = self.cohort([("001234", "01000001", "测试甲")])["patients"]
        result = match_file(self.root / "测试甲-病历.pdf", patients,
                            "/EMR/01000001/001234)\n住院号：1234\n入院日期：2020-01-01")
        self.assertEqual(result["match_status"], "matched")
        self.assertTrue(result["identifier_conflict"])
        self.assertIn("document_identifier_mismatch", [x["issue_type"] for x in result["match_issues"]])
        self.assertEqual(result["document_labelled_identifiers"]["inpatient_id"], ["1234"])

    def test_label_explicitly_pointing_to_other_cohort_patient_is_ambiguous(self):
        patients = self.cohort([("001234", "01000001", "测试甲"), ("001235", "01000002", "测试乙")])["patients"]
        result = match_file(self.root / "测试甲-病历.pdf", patients,
                            "/EMR/01000001/001234)\n住院号：001235")
        self.assertEqual(result["match_status"], "ambiguous")

    def test_shared_outpatient_alone_is_ambiguous(self):
        patients = self.cohort([("001234", "01000001", "测试甲"), ("001235", "01000001", "测试乙")])["patients"]
        result = match_file(self.root / "unknown.pdf", patients, "门诊号: 01000001")
        self.assertEqual(result["match_status"], "ambiguous")

    def test_placeholders_are_absent_without_dropping_rows(self):
        result = self.cohort([("000000", "暂无", "测试甲"), ("001235", "01000001", "测试乙")])
        self.assertEqual(len(result["patients"]), 2)
        self.assertFalse(result["patients"][0]["has_inpatient_id"])
        self.assertFalse(result["patients"][0]["has_outpatient_id"])
        self.assertEqual(normalize_identifier("001234.0"), "001234")
        self.assertEqual(normalize_identifier("000000.0"), "")
        self.assertEqual(normalize_identifier("0.0"), "")

    def test_exact_duplicate_pdf_keeps_all_sources_and_root_priority(self):
        patients = self.cohort([("001234", "01000001", "测试甲")])["patients"]
        first, second = self.root / "raw", self.root / "sample"
        first.mkdir(); second.mkdir()
        for root in (first, second):
            (root / "测试甲-病历.PDF").write_bytes(b"same synthetic bytes")
        result = scan_and_match([first, second], patients)
        self.assertEqual(result["n_files"], 2)
        self.assertEqual(result["n_unique_sha256"], 1)
        self.assertTrue(result["files"][0]["is_canonical"])
        self.assertEqual(result["files"][1]["duplicate_of"], result["files"][0]["document_id"])

    def test_same_patient_name_does_not_silently_merge(self):
        patients = self.cohort([("001234", "01000001", "测试甲"), ("001235", "01000002", "测试甲")])["patients"]
        self.assertEqual(match_file(self.root / "测试甲-病历.pdf", patients)["match_status"], "ambiguous")
        recovered = match_file(self.root / "测试甲-病历.pdf", patients, "/EMR/01000001/001234)")
        self.assertEqual(recovered["patient_id"], patients[0]["patient_id"])


if __name__ == "__main__":
    unittest.main()
