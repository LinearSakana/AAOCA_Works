from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from case_explorer.repository import CompatibilityError, SnapshotRegistry


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_run(root: Path, name: str, *, finished_at: str, extra_patient: bool = False) -> Path:
    run = root / name
    run.mkdir(parents=True)
    patients = [
        {
            "patient_id": "p_alpha",
            "n_sections": "2",
            "parse_status": "partial",
            "earliest_document_date": "2024-01-02",
            "latest_document_date": "2024-02-03",
            "future_manifest_field": "kept",
        }
    ]
    if extra_patient:
        patients.append({"patient_id": "p_beta", "n_sections": "0", "parse_status": "no_pdf_in_scope"})
    documents = [
        {
            "patient_id": "p_alpha",
            "document_id": "doc_alpha",
            "source_pdf": str(run / "source.pdf"),
            "page_count": "2",
            "n_sections": "2",
            "document_type": "mixed",
            "parse_status": "partial",
            "raw_parse_status": "text_layer_unusable",
            "ocr_recovered_page_count": "2",
            "flags": '["ocr_unverified"]',
            "future_document_field": "visible",
        }
    ]
    sections = [
        {
            "patient_id": "p_alpha",
            "document_id": "doc_alpha",
            "section_id": "sec_new_type",
            "text_path": "sections/doc_alpha.json",
            "section_type": "future_new_type",
            "section_subtype": "future_subtype",
            "section_title": "Future section",
            "section_date": "2024-01-02",
            "date_precision": "day",
            "page_start": "1",
            "page_end": "1",
            "parse_status": "ok",
            "text_source": "pdf_text_layer",
            "future_section_column": "preserved",
        },
        {
            "patient_id": "p_alpha",
            "document_id": "doc_alpha",
            "section_id": "sec_undated",
            "text_path": "sections/doc_alpha.json",
            "section_type": "progress",
            "section_subtype": "daily_progress",
            "section_title": "Progress",
            "section_date": "",
            "page_start": "2",
            "page_end": "2",
            "parse_status": "uncertain",
            "text_source": "local_ocr",
            "date_requires_review": "True",
        },
    ]
    write_csv(run / "patient_manifest.csv", patients)
    write_csv(run / "document_index.csv", documents)
    write_csv(run / "section_index.csv", sections)
    (run / "sections").mkdir()
    (run / "sections" / "doc_alpha.json").write_text(
        json.dumps(
            {
                "sections": [
                    {
                        **sections[0],
                        "text": "Example future section text",
                        "future_json_field": {"available": True},
                    },
                    {**sections[1], "text": "Undated OCR text"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run / "source.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (run / "run_metadata.json").write_text(
        json.dumps(
            {
                "pipeline_version": "test",
                "run_id": name,
                "status": "complete",
                "finished_at": finished_at,
                "summary": {"source_hash_verification": "passed"},
            }
        ),
        encoding="utf-8",
    )
    return run


def build_sidecar(root: Path, run: Path) -> Path:
    sidecar = root / "management_dynamic"
    write_csv(
        sidecar / "management_summary.csv",
        [
            {
                "patient_id": "p_alpha",
                "observed_management": "future_state",
                "actual_aaoca_surgery": "unknown",
                "management_confidence": "medium",
                "review_required": "True",
            }
        ],
    )
    write_csv(sidecar / "surgery_events.csv", [])
    (sidecar / "run_metadata.json").write_text(
        json.dumps(
            {
                "schema_version": "test_sidecar_v1",
                "source_hashes": {
                    "run_metadata": sha256(run / "run_metadata.json"),
                    "patient_manifest": sha256(run / "patient_manifest.csv"),
                    "section_index": sha256(run / "section_index.csv"),
                },
            }
        ),
        encoding="utf-8",
    )
    return sidecar


class SnapshotRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_dynamic_dimensions_fallback_timeline_and_extra_fields(self) -> None:
        run = build_run(self.root, "run_a", finished_at="2026-01-01T00:00:00Z")
        build_sidecar(self.root, run)
        registry = SnapshotRegistry(self.root, run=run, reload_interval=0)
        bootstrap = registry.bootstrap()
        self.assertIn("future_new_type", bootstrap["schema"]["section_types"])
        self.assertIn("future_subtype", bootstrap["schema"]["section_subtypes"])
        self.assertEqual(bootstrap["capabilities"]["timeline_source"], "derived_from_sections")
        self.assertTrue(bootstrap["capabilities"]["management_sidecar"])
        self.assertIn("future_state", bootstrap["schema"]["management_statuses"])
        patients = registry.snapshot().list_patients(section_type="future_new_type", management="future_state")
        self.assertEqual(patients["total"], 1)
        detail = registry.snapshot().patient_detail("p_alpha")
        self.assertEqual(detail["timeline"][0]["section_id"], "sec_new_type")
        section = registry.snapshot().section_detail("sec_new_type")
        self.assertEqual(section["text"], "Example future section text")
        self.assertEqual(section["extra_fields"]["future_json_field"], {"available": True})

    def test_discovers_and_switches_completed_runs(self) -> None:
        first = build_run(self.root, "run_old", finished_at="2026-01-01T00:00:00Z")
        second = build_run(self.root, "run_new", finished_at="2026-02-01T00:00:00Z", extra_patient=True)
        registry = SnapshotRegistry(self.root, reload_interval=0)
        self.assertEqual(registry.snapshot().run_path, second.resolve())
        self.assertEqual(registry.bootstrap()["overview"]["totals"]["patients"], 2)
        old_key = next(item["key"] for item in registry.runs_public() if item["label"] == first.name)
        registry.select(old_key)
        self.assertEqual(registry.snapshot().run_path, first.resolve())
        self.assertEqual(registry.bootstrap()["overview"]["totals"]["patients"], 1)

    def test_atomic_reload_uses_new_complete_data(self) -> None:
        run = build_run(self.root, "run_a", finished_at="2026-01-01T00:00:00Z")
        registry = SnapshotRegistry(self.root, run=run, reload_interval=0)
        self.assertEqual(registry.bootstrap()["overview"]["totals"]["patients"], 1)
        rows, fields = [], []
        with (run / "patient_manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        rows.append({"patient_id": "p_gamma", "n_sections": "0", "parse_status": "no_pdf_in_scope"})
        with (run / "patient_manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        time.sleep(0.002)
        self.assertEqual(registry.bootstrap()["overview"]["totals"]["patients"], 2)

    def test_rejects_missing_core_key(self) -> None:
        run = build_run(self.root, "run_a", finished_at="2026-01-01T00:00:00Z")
        write_csv(run / "section_index.csv", [{"patient_id": "p_alpha", "document_id": "doc_alpha"}])
        with self.assertRaisesRegex(CompatibilityError, "missing required columns"):
            SnapshotRegistry(self.root, run=run)

    def test_ignores_hash_mismatched_sidecar(self) -> None:
        run = build_run(self.root, "run_a", finished_at="2026-01-01T00:00:00Z")
        sidecar = build_sidecar(self.root, run)
        metadata = json.loads((sidecar / "run_metadata.json").read_text(encoding="utf-8"))
        metadata["source_hashes"]["section_index"] = "0" * 64
        (sidecar / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        registry = SnapshotRegistry(self.root, run=run)
        self.assertFalse(registry.bootstrap()["capabilities"]["management_sidecar"])


if __name__ == "__main__":
    unittest.main()
