from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from aaoca_pipeline.io_utils import sha256_file, write_csv, write_json, write_text
from aaoca_pipeline.management import write_management_package
from aaoca_pipeline.management_llm import (
    LLM_INTERFACE_VERSION,
    execute_llm_requests,
    prepare_llm_request_package,
    reconcile_llm_responses,
    validate_llm_request_package,
    validate_llm_responses,
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
    def complete(self, request, response_schema):
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
