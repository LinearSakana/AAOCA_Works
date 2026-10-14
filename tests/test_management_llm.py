from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from aaoca_pipeline.io_utils import sha256_file, write_csv, write_json, write_text
from aaoca_pipeline.management import write_management_package
from aaoca_pipeline.management_llm import (
    LLM_INTERFACE_VERSION,
    execute_llm_requests,
    prepare_llm_request_package,
    reconcile_llm_responses,
    validate_llm_request_package,
    validate_llm_responses,
    validate_hybrid_package,
)


def _section(
    patient_id: str,
    section_id: str,
    text: str,
    *,
    day: str,
    section_type: str,
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


def _make_sources(root: Path) -> tuple[Path, Path, Path]:
    run = root / "run"
    review = root / "review"
    management = root / "management"
    sections = [
        _section(
            "p_surgery",
            "doc_surgery_s0001",
            "手术记录。手术时间：2024-01-02。术前诊断：AAOCA。手术名称：冠状动脉修补术。手术经过：术顺。",
            day="2024-01-02",
            section_type="procedure",
            subtype="surgery_record",
        ),
        _section(
            "p_intent",
            "doc_intent_s0001",
            "术前讨论。诊断AAOCA。拟施手术名称和方式：冠状动脉修补术 拟施麻醉方式：全身麻醉。",
            day="2024-02-02",
            section_type="procedure",
            subtype="preoperative_discussion",
        ),
        _section(
            "p_unknown",
            "doc_unknown_s0001",
            "冠状动脉起源异常，行多根导管冠状动脉造影评估，未见后续治疗结论。",
            day="2024-03-02",
            section_type="progress",
        ),
    ]
    write_json(run / "run_metadata.json", {"status": "complete"})
    write_csv(
        run / "patient_manifest.csv",
        [{"patient_id": patient_id, "n_pdf": 1} for patient_id in ["p_surgery", "p_intent", "p_unknown"]],
    )
    write_csv(run / "section_index.csv", sections)
    for section in sections:
        write_json(run / "sections" / f"{section['document_id']}.json", {"sections": [section]})
    write_csv(
        review / "exception_cases.csv",
        [],
        ["patient_id", "automatic_aaoca_judgment", "review_status", "final_aaoca_judgment"],
    )
    write_json(
        review / "run_metadata.json",
        {
            "human_deliverable_scope": "exception_patients_only",
            "exception_patients": 0,
            "nonexception_patients": 3,
            "source_run_metadata_sha256": sha256_file(run / "run_metadata.json"),
            "source_patient_manifest_sha256": sha256_file(run / "patient_manifest.csv"),
            "source_section_index_sha256": sha256_file(run / "section_index.csv"),
        },
    )
    write_management_package(run, review, management)
    return run, review, management


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    write_text(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def _citation(request: dict) -> dict:
    passage = request["case"]["source_passages"][0]
    end = min(12, len(passage["text"]))
    return {
        "passage_id": passage["passage_id"],
        "quote_start": 0,
        "quote_end": end,
        "quote": passage["text"][:end],
        "purpose": "supports assessment",
    }


def _response_for(request: dict) -> dict:
    deterministic = request["case"]["deterministic_summary"]
    citation = _citation(request)
    if deterministic["observed_management"] == "intended_surgery":
        evidence_id = next(
            row["evidence_id"]
            for row in request["case"]["deterministic_evidence"]
            if row["assertion"] == "intended" and row["event_kind"] != "diagnostic_procedure"
        )
        assessment = {
            "observed_management": "intended_surgery",
            "actual_aaoca_surgery": "unknown",
            "confidence": "medium",
            "rationale": "Only a planned AAOCA operation is supplied.",
            "deterministic_evidence_ids": [evidence_id],
            "citations": [citation],
            "surgery_events": [
                {
                    "event_label": "planned AAOCA operation",
                    "occurrence": "intended",
                    "aaoca_relation": "related",
                    "procedure_name": "冠状动脉修补术",
                    "procedure_types": ["coronary_repair"],
                    "date": "2024-02-02",
                    "date_precision": "day",
                    "deterministic_evidence_ids": [evidence_id],
                    "citations": [citation],
                }
            ],
            "uncertainties": ["Completion is not documented."],
            "requires_human_review": True,
        }
    else:
        # Simulate a model finding a possible missed completed operation in a
        # supplied passage. It is structurally admissible only as a human-review
        # candidate and must never auto-promote the deterministic unknown state.
        assessment = {
            "observed_management": "surgery",
            "actual_aaoca_surgery": "yes",
            "confidence": "low",
            "rationale": "The passage may describe completed treatment.",
            "deterministic_evidence_ids": [],
            "citations": [citation],
            "surgery_events": [
                {
                    "event_label": "possible missed operation",
                    "occurrence": "completed",
                    "aaoca_relation": "related",
                    "procedure_name": "",
                    "procedure_types": [],
                    "date": "",
                    "date_precision": "unknown",
                    "deterministic_evidence_ids": [],
                    "citations": [citation],
                }
            ],
            "uncertainties": ["Requires source review."],
            "requires_human_review": True,
        }
    return {
        "interface_version": LLM_INTERFACE_VERSION,
        "request_id": request["request_id"],
        "patient_id": request["patient_id"],
        "model_receipt": {"provider": "test", "model": "fake-structured-client", "run_id": "unit"},
        "assessment": assessment,
    }


class _FakeClient:
    def __init__(self):
        self.calls = 0

    def complete(self, request, response_schema):
        self.calls += 1
        self.response_schema_id = response_schema["$id"]
        return _response_for(request)


class ManagementLlmTests(unittest.TestCase):
    def test_prepare_is_local_bounded_and_source_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            requests = root / "requests"
            result = prepare_llm_request_package(
                management,
                run,
                review,
                requests,
                instructions="Custom local review instructions.",
                prompt_version="custom_test_prompt_v1",
            )
            self.assertEqual(result["validation"]["validation_status"], "passed")
            self.assertFalse(result["llm_invoked"])
            self.assertFalse(result["network_processing"])
            rows = _load_jsonl(requests / "requests.jsonl")
            self.assertEqual({row["patient_id"] for row in rows}, {"p_intent", "p_unknown"})
            self.assertTrue(all(row["prompt_version"] == "custom_test_prompt_v1" for row in rows))
            self.assertTrue(all(row["instructions"] == "Custom local review instructions." for row in rows))
            self.assertTrue(all(row["case"]["source_passages"] for row in rows))
            for row in rows:
                summary = row["case"]["deterministic_summary"]
                for evidence in row["case"]["deterministic_evidence"]:
                    self.assertIsInstance(evidence["matched_rule_ids"], list)
                for field in ("other_procedure_contexts", "other_procedure_categories", "management_complexity_flags",
                              "management_context_evidence_ids", "complex_case_review_reasons", "unrelated_procedure_names"):
                    self.assertIsInstance(summary[field], list)
            validation = validate_llm_request_package(requests, management, run)
            self.assertEqual(validation["validation_status"], "passed")

    def test_fake_client_response_validation_and_non_overwriting_reconcile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            requests = root / "requests"
            responses = root / "responses.jsonl"
            hybrid = root / "hybrid"
            prepare_llm_request_package(management, run, review, requests)
            client = _FakeClient()
            result = execute_llm_requests(requests, responses, client)
            self.assertEqual(result["validation_status"], "passed")
            self.assertEqual(client.response_schema_id, f"urn:{LLM_INTERFACE_VERSION}:response")
            reconciled = reconcile_llm_responses(management, requests, responses, hybrid)
            self.assertEqual(reconciled["counts"]["agreements"], 1)
            self.assertEqual(reconciled["counts"]["disagreements_requiring_review"], 1)
            with (hybrid / "hybrid_management_summary.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = {row["patient_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(rows["p_unknown"]["llm_management"], "surgery")
            self.assertEqual(rows["p_unknown"]["recommended_management"], "unknown")
            self.assertEqual(rows["p_unknown"]["comparison"], "disagreement_review")
            self.assertEqual(rows["p_surgery"]["comparison"], "no_response")
            self.assertEqual(validate_hybrid_package(hybrid, management, requests, responses, run_root=run)
                             ["validation_status"], "passed")

    def test_request_identity_changes_with_context_limits_and_rejects_old_responses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            first, second, repeated = (root / name for name in ("first", "second", "repeated"))
            prepare_llm_request_package(management, run, review, first)
            prepare_llm_request_package(management, run, review, repeated)
            prepare_llm_request_package(management, run, review, second, max_characters_per_section=30)
            original = _load_jsonl(first / "requests.jsonl")
            ids = {row["request_id"] for row in original}
            self.assertEqual(ids, {row["request_id"] for row in _load_jsonl(repeated / "requests.jsonl")})
            self.assertTrue(ids.isdisjoint({row["request_id"] for row in _load_jsonl(second / "requests.jsonl")}))
            responses = root / "old_responses.jsonl"
            _write_jsonl(responses, [_response_for(row) for row in original])
            result = validate_llm_responses(second, responses)
            self.assertEqual({row["code"] for row in result["errors"]}, {"response_request_not_found"})

    def test_changed_request_payload_and_legacy_identity_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            requests = root / "requests"
            prepare_llm_request_package(management, run, review, requests)
            rows = _load_jsonl(requests / "requests.jsonl")
            rows[0]["case"]["deterministic_summary"]["observed_management"] = "unknown"
            _write_jsonl(requests / "requests.jsonl", rows)
            result = validate_llm_request_package(requests, management, run)
            self.assertIn("request_content_id_mismatch", {row["code"] for row in result["errors"]})
            metadata = json.loads((requests / "run_metadata.json").read_text(encoding="utf-8"))
            metadata.pop("request_identity_version")
            write_json(requests / "run_metadata.json", metadata)
            result = validate_llm_request_package(requests)
            self.assertEqual(result["errors"][0]["code"], "request_identity_version_mismatch")

    def test_stale_management_is_blocked_before_execution_and_reconciliation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            requests, responses, hybrid = root / "requests", root / "responses.jsonl", root / "hybrid"
            prepare_llm_request_package(management, run, review, requests)
            execute_llm_requests(requests, responses, _FakeClient())
            reconcile_llm_responses(management, requests, responses, hybrid)
            metadata_path = management / "run_metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["revision"] = "a new run with the same patient states"
            write_json(metadata_path, metadata)
            client = _FakeClient()
            with self.assertRaisesRegex(ValueError, "source validation"):
                execute_llm_requests(requests, root / "new_responses.jsonl", client)
            self.assertEqual(client.calls, 0)
            self.assertFalse((root / "new_responses.jsonl").exists())
            with self.assertRaisesRegex(ValueError, "sources do not match"):
                reconcile_llm_responses(management, requests, responses, root / "new_hybrid")
            self.assertFalse((root / "new_hybrid").exists())
            result = validate_llm_responses(requests, responses, management_root=management)
            self.assertEqual(result["errors"][0]["code"], "response_request_package_invalid")
            result = validate_hybrid_package(hybrid, management, requests, responses)
            self.assertIn("hybrid_source_hash_mismatch", {row["code"] for row in result["errors"]})

    def test_hybrid_row_and_cached_receipt_tampering_are_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            requests, responses, hybrid = root / "requests", root / "responses.jsonl", root / "hybrid"
            prepare_llm_request_package(management, run, review, requests)
            execute_llm_requests(requests, responses, _FakeClient())
            reconcile_llm_responses(management, requests, responses, hybrid)
            with (hybrid / "hybrid_management_summary.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            next(row for row in rows if row["patient_id"] == "p_unknown")["recommended_management"] = "surgery"
            write_csv(hybrid / "hybrid_management_summary.csv", rows)
            write_json(hybrid / "response_validation.json", {"validation_status": "passed", "error_count": 0})
            result = validate_hybrid_package(hybrid, management, requests, responses)
            codes = {row["code"] for row in result["errors"]}
            self.assertIn("hybrid_row_mismatch", codes)
            self.assertIn("hybrid_validation_receipt_mismatch", codes)

    def test_output_overlap_never_modifies_upstream_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            requests, responses = root / "requests", root / "responses.jsonl"
            prepare_llm_request_package(management, run, review, requests)
            _write_jsonl(responses, [_response_for(row) for row in _load_jsonl(requests / "requests.jsonl")])
            before = {path: sha256_file(path) for folder in (run, management, requests)
                      for path in folder.rglob("*") if path.is_file()}
            client = _FakeClient()
            calls = [
                lambda: prepare_llm_request_package(management, run, review, management),
                lambda: reconcile_llm_responses(management, requests, responses, requests),
                lambda: execute_llm_requests(requests, requests / "requests.jsonl", client),
            ]
            for call in calls:
                with self.assertRaisesRegex(ValueError, "must not overlap"):
                    call()
            self.assertEqual(client.calls, 0)
            self.assertEqual(before, {path: sha256_file(path) for path in before})

    def test_missing_sources_return_validation_failure_before_client_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            requests = root / "requests"
            prepare_llm_request_package(management, run, review, requests)
            client = _FakeClient()
            with self.assertRaisesRegex(ValueError, "request_source_artifact_missing"):
                execute_llm_requests(requests, root / "responses.jsonl", client,
                                     management_root=root / "missing")
            self.assertEqual(client.calls, 0)

    def test_cli_validates_hybrid_and_reports_stale_source_with_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            requests, responses, hybrid = root / "requests", root / "responses.jsonl", root / "hybrid"
            prepare_llm_request_package(management, run, review, requests)
            execute_llm_requests(requests, responses, _FakeClient())
            reconcile_llm_responses(management, requests, responses, hybrid)
            command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve().parents[1] / "scripts/aaoca_management_llm.py"),
                       "validate-hybrid", "--output", str(hybrid), "--management", str(management),
                       "--requests", str(requests), "--responses", str(responses), "--run", str(run)]
            valid = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(json.loads(valid.stdout)["validation_status"], "passed")
            write_text(management / "run_metadata.json", (management / "run_metadata.json").read_text(encoding="utf-8") + "\n")
            stale = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(stale.returncode, 1, stale.stderr)
            self.assertIn("hybrid_source_hash_mismatch", {row["code"] for row in json.loads(stale.stdout)["errors"]})

    def test_hallucinated_citation_and_unsafe_disagreement_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, review, management = _make_sources(root)
            requests = root / "requests"
            responses = root / "responses.jsonl"
            prepare_llm_request_package(management, run, review, requests)
            request_rows = _load_jsonl(requests / "requests.jsonl")
            response_rows = [_response_for(row) for row in request_rows]
            unknown = next(row for row in response_rows if row["patient_id"] == "p_unknown")
            unknown["assessment"]["citations"][0]["quote"] += "hallucinated"
            unknown["assessment"]["requires_human_review"] = False
            _write_jsonl(responses, response_rows)
            result = validate_llm_responses(requests, responses, require_complete=True)
            self.assertEqual(result["validation_status"], "failed")
            codes = {row["code"] for row in result["errors"]}
            self.assertIn("citation_quote_mismatch", codes)
            self.assertIn("new_surgery_claim_requires_human_review", codes)
            self.assertIn("llm_disagreement_requires_human_review", codes)


if __name__ == "__main__":
    unittest.main()
