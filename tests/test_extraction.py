"""Synthetic regression cases; no patient content is checked into source code."""

import tempfile
import unittest
from pathlib import Path

import fitz

from aaoca_pipeline.extraction import _quality, extract_pdf
from aaoca_pipeline.normalization import normalize_document, normalize_text
from aaoca_pipeline.local_ocr import apply_local_ocr


class ExtractionTests(unittest.TestCase):
    def test_outlined_chinese_cannot_pass_with_nonempty_numbers(self):
        status, flags = _quality("123 456 789 " * 60, {
            "paint_operation_count": 950, "character_sized_vector_paths": 800,
        })
        self.assertEqual(status, "text_layer_unusable")
        self.assertIn("vector_outlined_text_suspected", flags)

    def test_numeric_laboratory_page_is_not_rejected_by_low_cjk_ratio(self):
        status, _ = _quality("检验报告 白细胞 " + "123.4 456.7 " * 100, {
            "paint_operation_count": 100, "character_sized_vector_paths": 0,
        })
        self.assertEqual(status, "ok")

    def test_blank_and_visual_but_empty_are_different(self):
        self.assertEqual(_quality("", {"paint_operation_count": 0})[0], "empty")
        status, flags = _quality("", {"paint_operation_count": 30, "character_sized_vector_paths": 30})
        self.assertEqual(status, "text_layer_unusable")
        self.assertIn("text_layer_missing", flags)

    def test_real_pdf_page_boundaries_and_off_page_text_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pdf"
            doc = fitz.open()
            page = doc.new_page(width=200, height=200)
            page.insert_text((20, 40), "Clinical text " * 5, fontsize=12)
            page.insert_text((220, 70), "OFF_PAGE_SENTINEL", fontsize=12)
            doc.new_page(width=200, height=200)
            doc.save(path)
            doc.close()
            result = extract_pdf(path)
            self.assertEqual(result["page_count"], 2)
            self.assertIn("OFF_PAGE_SENTINEL", result["pages"][0]["text"])
            self.assertIn("off_page_text", result["pages"][0]["flags"])
            self.assertEqual(result["pages"][1]["extraction_status"], "empty")
            self.assertEqual(result["pages"][1]["page"], 2)
            self.assertGreater(result["extracted_character_count"], 40)

    def test_corrupt_pdf_is_failure_without_path_in_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private_identifier.pdf"
            path.write_bytes(b"not a PDF")
            result = extract_pdf(path)
            self.assertEqual(result["parse_status"], "failed")
            self.assertNotIn("private_identifier", str(result))

    def test_raw_text_and_repeated_clinical_headers_survive_normalization(self):
        raw = "病历文书 - 360视图 v2.1 Beta\n入院记录\n日期: 2020-01-01\n\n\n入院记录\n剂量: １．２ mg\nhttps://example.invalid/report\n1/2\n"
        result = normalize_document({"pages": [{"page": 1, "text": raw}]})
        page = result["pages"][0]
        self.assertEqual(page["text"], raw)
        self.assertEqual(page["normalized_text"].count("入院记录"), 2)
        self.assertIn("1.2 mg", page["normalized_text"])
        self.assertNotIn("https://", page["normalized_text"])
        self.assertEqual(len(page["normalized_text"].splitlines()), len(page["normalized_line_map"]))
        self.assertEqual(len(page["removed_lines"]), 3)

    def test_ocr_representation_never_overwrites_pdf_raw_text(self):
        result = normalize_document({"pages": [{
            "page": 1, "text": "123", "analysis_text": "入院记录 123",
            "analysis_text_source": "local_ocr",
        }]})
        self.assertEqual(result["pages"][0]["text"], "123")
        self.assertEqual(result["pages"][0]["normalized_text"], "入院记录 123")
        self.assertEqual(result["pages"][0]["normalized_text_source"], "local_ocr")

    def test_ocr_is_not_invoked_for_pages_with_working_text(self):
        class Engine:
            provenance = {"method": "synthetic"}

            def recognize(self, page):
                raise AssertionError("OCR must not be invoked")

        result = apply_local_ocr(Path("does_not_exist.pdf"), {
            "parse_status": "ok", "pages": [{"ocr_recommended": False}],
        }, Engine())
        self.assertEqual(result["ocr_attempted_page_count"], 0)

    def test_ocr_failure_preserves_raw_status_and_text(self):
        class Engine:
            provenance = {"method": "synthetic"}

            def recognize(self, page):
                raise RuntimeError("synthetic failure")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(path)
            doc.close()
            result = apply_local_ocr(path, {
                "parse_status": "text_layer_unusable", "flags": [], "pages": [{
                    "page": 1, "text": "123", "ocr_recommended": True,
                    "extraction_status": "text_layer_unusable", "flags": [],
                }],
            }, Engine())
        self.assertEqual(result["parse_status"], "text_layer_unusable")
        self.assertEqual(result["pages"][0]["text"], "123")
        self.assertEqual(result["pages"][0]["ocr_status"], "failed")
        self.assertEqual(result["ocr_pending_page_count"], 1)


if __name__ == "__main__":
    unittest.main()
