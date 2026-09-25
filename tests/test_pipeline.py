"""Synthetic end-to-end tests and independent artifact validation.

All fixtures are created under TemporaryDirectory. They include readable,
blank, zero-page, corrupt, duplicated, and conflicting-identity PDFs. No real
patient material is copied into tests or sent to an external service.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from pypdf import PdfWriter

from aaoca_pipeline.io_utils import sha256_file, validate_output_locations
from aaoca_pipeline.pipeline import run_pipeline
from aaoca_pipeline.matching import scan_and_match

_SPEC = importlib.util.spec_from_file_location("independent_output_validator", Path(__file__).resolve().parents[1] / "scripts" / "validate_outputs.py")
_VALIDATOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VALIDATOR)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.close_log_handlers)
        self.root = Path(self.temp.name)
        self.raw, self.alias, self.cohort = (self.root / name for name in ("raw", "sample", "cohort"))
        for directory in (self.raw, self.alias, self.cohort):
            directory.mkdir()
        self.csv_path = self.cohort / "patients.csv"
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["住院号", "门诊号", "姓名", "病历", "检验"])
            for i, name in enumerate(("测试甲", "测试乙", "测试丙", "测试丁", "测试戊"), 1):
                writer.writerow([f"10000{i}", f"1000000{i}", name, 1, 0])
        self.output = self.root / "output"
        self.settings = {"cohort_csv": str(self.csv_path), "pdf_roots": [str(self.raw), str(self.alias)],
                         "output_root": str(self.output), "cache_root": str(self.root / "cache"),
                         "scope": "synthetic_test", "verify_source_hashes": True}

    @staticmethod
    def close_log_handlers():
        # Windows cannot remove an output log while a FileHandler is open.
        logger = logging.getLogger("aaoca_pipeline")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def pdf(self, path, text):
        doc = fitz.open()
        page = doc.new_page()
        if text:
            page.insert_text((30, 40), text, fontname="china-s", fontsize=10)
        doc.save(path)
        doc.close()

    def populate(self):
        first = self.raw / "测试甲-病历.pdf"
        self.pdf(first, "2020-01-02 10:00 首次病程记录\n记录日期：2020-01-02\n"
                 + "合成研究测试内容，患者情况平稳。\n" * 8)
        (self.alias / first.name).write_bytes(first.read_bytes())
        self.pdf(self.raw / "测试乙-病历.pdf", "")
        (self.raw / "测试丙-病历.pdf").write_bytes(b"this is a synthetic invalid PDF")
        writer = PdfWriter()
        writer.write(str(self.raw / "测试丁-病历.pdf"))

    def source_hashes(self):
        files = [self.csv_path] + list(self.raw.glob("*.pdf")) + list(self.alias.glob("*.pdf"))
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

    def test_real_end_to_end_handles_empty_corrupt_zero_page_and_duplicate(self):
        self.populate()
        before = self.source_hashes()
        summary = run_pipeline(self.settings)
        self.assertEqual(self.source_hashes(), before)
        self.assertEqual(summary["source_pdf_files"], 5)
        self.assertEqual(summary["unique_pdf_contents"], 4)
        self.assertEqual(summary["exact_duplicate_copies"], 1)
        self.assertEqual(summary["patients_without_pdf"], 1)
        self.assertEqual(summary["source_hash_verification"], "passed")
        docs = read_csv(self.output / "document_index.csv")
        self.assertTrue(any(d["parse_status"] == "failed" for d in docs))
        self.assertTrue(any(d["page_count"] == "0" for d in docs))
        self.assertTrue(any(d["document_type"] == "nonclinical" for d in docs))
        events = read_csv(self.output / "patient_timeline.csv")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_subtype"], "initial_progress")
        self.assertEqual(next(s for s in read_csv(self.output / "section_index.csv")
                              if s["section_id"] == events[0]["section_id"])["section_subtype"], "initial_progress")
        self.assertTrue(all(s["section_type"] != "nonclinical"
                            for s in read_csv(self.output / "qc" / "uncertain_documents.csv")))
        duplicate_ids = {d["document_id"] for d in docs if d["duplicate_of"]}
        self.assertFalse({t["document_id"] for t in events} & duplicate_ids)
        result = _VALIDATOR.validate_outputs(self.output)
        self.assertEqual(result["validation_status"], "passed", result)
        rerun = run_pipeline(self.settings)
        self.assertEqual(rerun["extraction_cache_hits"], 4)
        self.assertEqual(self.source_hashes(), before)
        self.assertEqual(read_csv(self.output / "patient_timeline.csv"), events)

    def test_duplicate_content_assigned_to_two_patients_cannot_enter_timeline(self):
        first = self.raw / "测试甲-病历.pdf"
        self.pdf(first, "2020-01-02 10:00 首次病程记录\n" + "合成病例文本。\n" * 15)
        (self.raw / "测试乙-病历.pdf").write_bytes(first.read_bytes())
        summary = run_pipeline(self.settings)
        self.assertEqual(summary["timeline_events"], 0)
        docs = read_csv(self.output / "document_index.csv")
        self.assertTrue(all(not d["patient_id"] for d in docs))
        self.assertTrue(all(d["match_status"] == "ambiguous_duplicate_identity" for d in docs))
        self.assertEqual(_VALIDATOR.validate_outputs(self.output)["validation_status"], "passed")

    def test_validator_detects_incorrect_section_text_and_count(self):
        self.populate()
        run_pipeline(self.settings)
        documents = read_csv(self.output / "document_index.csv")
        valid = next(d for d in documents if d["parse_status"] == "ok" and not d["duplicate_of"])
        path = self.output / valid["sections_path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["sections"][0]["text"] += "\nSYNTHETIC_TAMPERING"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = _VALIDATOR.validate_outputs(self.output)
        self.assertGreater(result["error_types"].get("section_text_not_equal_to_normalized_spans", 0), 0)

    def test_output_and_cache_cannot_overlap_any_raw_input_directory(self):
        for invalid in (self.raw, self.raw / "nested", self.root, self.cohort / "generated"):
            with self.subTest(kind=invalid.name):
                with self.assertRaises(ValueError):
                    validate_output_locations([invalid], [self.raw, self.alias], self.csv_path)
        validate_output_locations([self.output, self.root / "cache"], [self.raw, self.alias], self.csv_path)

    def test_two_unreadable_sources_are_not_deduplicated_or_cached(self):
        for name in ("测试甲", "测试乙"):
            self.pdf(self.raw / f"{name}-病历.pdf", "Synthetic source should not be read after scan failure")

        def simulated_scan_failure(roots, patients):
            result = scan_and_match(roots, patients)
            for record in result["files"]:
                record.update(sha256="", scan_status="failed", duplicate_of="", is_canonical=True)
                result["issues"].append({"issue_type": "file_read_failure", "severity": "error",
                                         "document_id": record["document_id"], "details": "Synthetic permission failure"})
            return result

        with patch("aaoca_pipeline.matching.scan_and_match", side_effect=simulated_scan_failure):
            summary = run_pipeline(self.settings)
        self.assertEqual(summary["unique_pdf_contents"], 2)
        self.assertEqual(summary["exact_duplicate_copies"], 0)
        self.assertEqual(summary["extraction_cache_hits"], 0)
        self.assertEqual(summary["source_hash_verification"], "partially_unverifiable")
        self.assertEqual(summary["source_unverifiable_count"], 2)
        docs = read_csv(self.output / "document_index.csv")
        self.assertEqual(len({d["raw_text_path"] for d in docs}), 2)
        self.assertTrue(all(d["parse_status"] == "failed" for d in docs))
        self.assertTrue(all(not d["duplicate_of"] for d in docs))
        self.assertFalse(list((self.root / "cache").rglob("*.json")))
        self.assertEqual(_VALIDATOR.validate_outputs(self.output)["validation_status"], "passed")

    def test_final_hash_permission_error_is_reported_without_claiming_integrity(self):
        self.pdf(self.raw / "测试甲-病历.pdf", "2020-01-02 10:00 首次病程记录\n" + "合成病例文本。\n" * 15)

        def final_permission_error(path):
            if Path(path).suffix.lower() == ".pdf":
                raise PermissionError("synthetic inaccessible source")
            return sha256_file(path)

        with patch("aaoca_pipeline.pipeline.sha256_file", side_effect=final_permission_error):
            summary = run_pipeline(self.settings)
        self.assertEqual(summary["source_hash_verification"], "partially_unverifiable")
        self.assertEqual(summary["source_unverifiable_count"], 1)
        inventory = read_csv(self.output / "source_inventory.csv")
        pdf_row = next(row for row in inventory if row["kind"] == "pdf")
        self.assertEqual(pdf_row["unchanged"], "")
        self.assertEqual(pdf_row["verification_error"], "PermissionError")
        self.assertEqual(_VALIDATOR.validate_outputs(self.output)["validation_status"], "passed")


if __name__ == "__main__":
    unittest.main()
