"""Synthetic Gold Set tests; no clinical PDFs or copied patient text."""
from __future__ import annotations

import csv
from itertools import product
import json
from pathlib import Path
import tempfile
import unittest

from aaoca_pipeline.gold_common import (SCHEMA, SAMPLE_SCHEMA, digest, freeze,
                                        sample, validate_annotation, write_json)
from aaoca_pipeline.gold_evaluate import compare, edit_distance, evaluate
from aaoca_pipeline.gold_review import _seed


def csv_file(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def reference_edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        next_row = [i]
        for j, other in enumerate(b, 1):
            next_row.append(min(next_row[j - 1] + 1, row[j] + 1,
                                row[j - 1] + (char != other)))
        row = next_row
    return row[-1]


class GoldSetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / "run_a"
        self.gold = self.root / "gold"
        self.output.mkdir()
        write_json(self.output / "run_metadata.json", {
            "status": "complete", "run_id": "synthetic_a", "pipeline_version": "0.1.0",
            "code_changed_during_run": False, "code_sha256": {"structure.py": "abc"},
            "summary": {"source_hash_verification": "passed"}})

    def make_output(self):
        docs, pages, sections = [], [], []
        for index, (source, family) in enumerate(product(("native", "ocr"), ("record", "lab")), 1):
            document_id, sha = f"doc_{index}", f"{index:064x}"
            text = "A\nB" if index == 1 else "报告\n2024-01-02"
            docs.append({"document_id": document_id, "sha256": sha, "duplicate_of": "",
                         "patient_id": f"P{index}", "relative_source": f"synthetic_{'检验' if family == 'lab' else '病历'}.pdf",
                         "source_pdf": str(self.root / f"synthetic_{index}.pdf"),
                         "text_path": f"normalized/{document_id}.txt", "sections_path": f"sections/{document_id}.json"})
            pages.append({"document_id": document_id, "page": 1,
                          "analysis_text_source": "local_ocr" if source == "ocr" else "pdf_text_layer",
                          "normalized_character_count": len(text), "ocr_low_confidence_line_count": 1 if source == "ocr" else 0,
                          "flags": "[]"})
            sec = {"section_id": f"s{index}", "page_spans": [{"page": 1, "start_line": 1, "end_line": 2}],
                   "section_type": "progress" if index == 1 else "laboratory" if family == "lab" else "admission",
                   "section_subtype": "", "section_date": "" if index == 1 else "2024-01-03" if index == 2 else "2024-01-02",
                   "date_source": "test_timestamp_column" if family == "lab" else "title_timestamp",
                   "date_uncertain": False, "date_evidence": "", "leakage_flags": []}
            write_json(self.output / "normalized" / f"{document_id}.json",
                       {"pages": [{"page": 1, "normalized_text": text}]})
            write_json(self.output / "sections" / f"{document_id}.json", {"sections": [sec]})
            sections.append({"document_id": document_id, "page_start": 1, "page_end": 1,
                             "section_type": sec["section_type"], "date_uncertain": False,
                             "section_date": sec["section_date"], "flags": "[]",
                             "leakage_flags": "[]"})
        csv_file(self.output / "document_index.csv", docs)
        csv_file(self.output / "page_index.csv", pages)
        csv_file(self.output / "section_index.csv", sections)
        return docs

    def annotation(self, unit, text, sections):
        return {"schema_version": SCHEMA, "sample_id": self.manifest["sample_id"],
                "unit_id": unit["unit_id"], "source_sha256": unit["source_sha256"], "page": unit["page"],
                "status": "complete", "reviewer": "synthetic", "reviewed_at": "2026-01-01T00:00:00Z",
                "notes": "", "text": {"status": "ok", "impact": "low", "gold_text": text}, "sections": sections}

    @staticmethod
    def section(start, end, kind, date_status="absent", date_value="", date_role="document", other_dates=None):
        return {"start_line": start, "end_line": end, "type": {"status": "known", "value": kind},
                "subtype": {"status": "known", "value": ""}, "date": {
                    "status": date_status, "value": date_value, "role": date_role, "evidence": "",
                    "other_dates": other_dates or []}, "impact": "moderate", "notes": ""}

    def test_exact_edit_distance(self):
        alphabet = ("A", "B", "中")
        words = ["".join(chars) for length in range(5) for chars in product(alphabet, repeat=length)]
        for a in words:
            for b in words[::9]:
                self.assertEqual(edit_distance(a, b), reference_edit_distance(a, b), (a, b))

    def test_sampling_freeze_scoring_and_fair_comparison(self):
        docs = self.make_output()
        self.manifest = sample(self.output, self.gold, pages_per_stratum=1, seed=7)
        self.assertEqual(len(self.manifest["units"]), 4)
        self.assertEqual(len({u["stratum"] for u in self.manifest["units"]}), 4)
        for unit in self.manifest["units"]:
            index = int(unit["baseline_document_id"].split("_")[1])
            if index == 1:
                annotation = self.annotation(unit, "A\nB", [self.section(1, 1, "progress"), self.section(2, 2, "procedure")])
            else:
                family = "lab" if index in (2, 4) else "record"
                annotation = self.annotation(unit, "报告\n2024-01-02", [self.section(
                    1, 2, "laboratory" if family == "lab" else "admission", "known", "2024-01-02",
                    "test" if family == "lab" else "document",
                    [{"value": "2024-01-03", "role": "print", "evidence": "synthetic print date"}] if index == 2 else [])])
            self.assertEqual(validate_annotation(annotation, unit, self.manifest["sample_id"]), [])
            write_json(self.gold / "annotations" / f"{unit['unit_id']}.json", annotation)
        receipt = freeze(self.gold, "r1")
        self.assertEqual(receipt["reviewed_pages"], 4)
        first = evaluate(self.gold, "r1", self.output)
        self.assertEqual(first["metrics"]["text_cer"], 0)
        self.assertEqual(first["metrics"]["boundary_tolerant_f1"], 0)
        self.assertEqual(first["metrics"]["section_match_recall"], 0.8)
        self.assertIn("missed_boundary", first["failure_modes"])
        self.assertIn("missed_section", first["failure_modes"])
        self.assertIn("date_confused_with_print", first["failure_modes"])
        self.assertEqual(first["metrics"]["date_value_accuracy_known"], 0.666667)
        second = evaluate(self.gold, "r1", self.output)
        self.assertEqual(compare(first, second)["delta_right_minus_left"]["text_cer"], 0)
        second["annotation_digest"] = "wrong"
        with self.assertRaises(ValueError):
            compare(first, second)
        # The frozen revision detects any later label change.
        target = self.gold / "revisions" / "r1" / f"{self.manifest['units'][0]['unit_id']}.json"
        changed = json.loads(target.read_text(encoding="utf-8"))
        changed["notes"] = "changed"
        write_json(target, changed)
        with self.assertRaises(ValueError):
            evaluate(self.gold, "r1", self.output)

    def test_uncertain_and_schema_gap_are_allowed(self):
        unit = {"unit_id": "pg_1", "source_sha256": "a" * 64, "page": 1}
        self.manifest = {"sample_id": "sample"}
        annotation = self.annotation(unit, "临床文本", [self.section(1, 1, "unknown")])
        annotation["sections"][0]["type"] = {"status": "schema_gap", "value": ""}
        annotation["sections"][0]["date"] = {"status": "uncertain", "value": "", "role": "other", "other_dates": []}
        self.assertEqual(validate_annotation(annotation, unit, "sample"), [])
        annotation["sections"] = []
        self.assertIn("complete annotation must cover each nonempty gold line exactly once",
                      validate_annotation(annotation, unit, "sample"))
        seeded = _seed(unit, {"normalized_text": "A\nB"}, [{"start_line": 1, "end_line": 2,
                   "section_type": "progress", "section_subtype": "", "section_date": "", "date_source": ""}], "sample")
        self.assertEqual(seeded["status"], "draft")


if __name__ == "__main__":
    unittest.main()
