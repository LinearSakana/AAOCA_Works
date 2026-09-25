"""Provider-neutral LLM middleware for AAOCA management review.

This module deliberately contains no endpoint, SDK, API key handling or
provider-specific message format.  It prepares local, provenance-bearing JSONL
requests; an injected client may later turn those requests into structured
responses.  Responses are mechanically checked against the exact evidence IDs
and source passages supplied to the model before they can enter a sidecar
reconciliation artifact.

The deterministic management package remains the authoritative standalone
result.  Reconciliation never overwrites it in place and never silently
promotes an LLM disagreement to a completed operation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, Protocol

from .io_utils import sha256_file, write_csv, write_json, write_text
from .management import (
    AAOCA_ANCHOR_RE,
    MANAGEMENT_VALUES,
    SURGERY_STATUS_VALUES,
    _bool,
    _json_list,
    _stable_id,
    load_sections,
    validate_management_package,
)


LLM_INTERFACE_VERSION = "aaoca_management_llm_v1"
PROMPT_VERSION = "aaoca_management_review_prompt_v1"

REQUEST_MANIFEST_FIELDS = [
    "request_id",
    "patient_id",
    "selection_policy",
    "deterministic_management",
    "deterministic_actual_aaoca_surgery",
    "n_available_evidence_rows",
    "n_included_evidence_rows",
    "n_omitted_evidence_rows",
    "n_available_sections",
    "n_included_sections",
    "n_passages",
    "included_passage_characters",
    "context_truncated",
]

HYBRID_FIELDS = [
    "patient_id",
    "deterministic_management",
    "deterministic_actual_aaoca_surgery",
    "deterministic_confidence",
    "deterministic_review_required",
    "llm_response_present",
    "llm_management",
    "llm_actual_aaoca_surgery",
    "llm_confidence",
    "llm_requires_human_review",
    "llm_deterministic_evidence_ids",
    "llm_citation_count",
    "comparison",
    "recommended_management",
    "recommended_actual_aaoca_surgery",
    "recommendation_rule",
    "review_required",
    "review_reasons",
]

MANAGEMENT_CUE_RE = re.compile(
    r"手术记录|手术名称|手术方式|手术时间|术后|既往.{0,20}(?:手术|行)|"
    r"拟(?:行|施|定)|计划|建议|考虑|手术指征|知情同意|术前讨论|"
    r"取消|暂缓|拒绝|放弃|未行|未处理|未予处理|不予处理|保守治疗|随访|"
    r"冠(?:状动)?脉造影|心导管",
    re.I | re.DOTALL,
)

PROMPT_TEMPLATE = """# AAOCA management structured review

You review one patient's supplied excerpts only. Determine what actually
happened in relation to AAOCA; do not decide what should happen clinically.

Rules:

1. `surgery` requires evidence that an AAOCA-related therapeutic operation was
   completed. Recommendation, consideration, booking, consent and preoperative
   discussion are not completion.
2. Coronary angiography, aortography and cardiac catheterisation are diagnostic
   procedures, even when the source calls them an operation.
3. A completed ASD/VSD/PDA/valve/vascular-ring or other operation is not an
   AAOCA operation merely because AAOCA is mentioned in the same record.
4. `intended_surgery` means AAOCA surgery was recommended, considered,
   planned, consented, cancelled or declined, but completion is not proven.
5. `conservative` needs affirmative non-operative/observation evidence.
   Absence of a surgery record never proves conservative treatment or
   `actual_aaoca_surgery=no`.
6. Use `unknown` whenever the supplied evidence is insufficient or conflicting.
7. Preserve multiple operations, date precision and conflicts. Do not merge
   different dated operations or invent a missing day.
8. Every factual conclusion must cite a supplied deterministic evidence ID
   and/or an exact source passage span. Quotes must be copied exactly.
9. Return only an object conforming to the supplied response schema. Do not
   include identifiers or facts absent from the request.
"""


REQUEST_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"urn:{LLM_INTERFACE_VERSION}:request",
    "type": "object",
    "required": [
        "interface_version",
        "prompt_version",
        "request_id",
        "patient_id",
        "instructions",
        "case",
        "response_schema_id",
    ],
    "properties": {
        "interface_version": {"const": LLM_INTERFACE_VERSION},
        "prompt_version": {"type": "string", "minLength": 1},
        "request_id": {"type": "string"},
        "patient_id": {"type": "string"},
        "instructions": {"type": "string"},
        "case": {"type": "object"},
        "response_schema_id": {"const": f"urn:{LLM_INTERFACE_VERSION}:response"},
    },
    "additionalProperties": False,
}


RESPONSE_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"urn:{LLM_INTERFACE_VERSION}:response",
    "type": "object",
    "required": [
        "interface_version",
        "request_id",
        "patient_id",
        "model_receipt",
        "assessment",
    ],
    "properties": {
        "interface_version": {"const": LLM_INTERFACE_VERSION},
        "request_id": {"type": "string"},
        "patient_id": {"type": "string"},
        "model_receipt": {
            "type": "object",
            "required": ["provider", "model"],
            "properties": {
                "provider": {"type": "string"},
                "model": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "assessment": {
            "type": "object",
            "required": [
                "observed_management",
                "actual_aaoca_surgery",
                "confidence",
                "rationale",
                "deterministic_evidence_ids",
                "citations",
                "surgery_events",
                "uncertainties",
                "requires_human_review",
            ],
            "properties": {
                "observed_management": {"enum": sorted(MANAGEMENT_VALUES)},
                "actual_aaoca_surgery": {"enum": sorted(SURGERY_STATUS_VALUES)},
                "confidence": {"enum": ["high", "medium", "low"]},
                "rationale": {"type": "string"},
                "deterministic_evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "uniqueItems": True,
                },
                "citations": {"type": "array", "items": {"$ref": "#/$defs/citation"}},
                "surgery_events": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/surgery_event"},
                },
                "uncertainties": {"type": "array", "items": {"type": "string"}},
                "requires_human_review": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    "$defs": {
        "citation": {
            "type": "object",
            "required": ["passage_id", "quote_start", "quote_end", "quote", "purpose"],
            "properties": {
                "passage_id": {"type": "string"},
                "quote_start": {"type": "integer", "minimum": 0},
                "quote_end": {"type": "integer", "minimum": 0},
                "quote": {"type": "string"},
                "purpose": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "surgery_event": {
            "type": "object",
            "required": [
                "event_label",
                "occurrence",
                "aaoca_relation",
                "procedure_name",
                "procedure_types",
                "date",
                "date_precision",
                "deterministic_evidence_ids",
                "citations",
            ],
            "properties": {
                "event_label": {"type": "string"},
                "occurrence": {"enum": ["completed", "intended", "cancelled_or_declined"]},
                "aaoca_relation": {"enum": ["related", "unrelated", "uncertain"]},
                "procedure_name": {"type": "string"},
                "procedure_types": {"type": "array", "items": {"type": "string"}},
                "date": {"type": "string"},
                "date_precision": {"enum": ["day", "month", "year", "unknown"]},
                "deterministic_evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "uniqueItems": True,
                },
                "citations": {"type": "array", "items": {"$ref": "#/$defs/citation"}},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


class StructuredManagementLLMClient(Protocol):
    """Provider adapter seam; implementations may call any approved endpoint.

    The adapter is responsible only for translating this provider-neutral
    request and JSON schema to its SDK, then returning a parsed response dict.
    Patient data must not be sent anywhere until that endpoint is separately
    approved by the data owner.
    """

    def complete(self, request: Mapping[str, object], response_schema: Mapping[str, object]) -> Mapping[str, object]:
        ...


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record must be an object at {path}:{line_number}")
            rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    payload = "".join(json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    write_text(path, payload)


def _decode_row(row: dict[str, str], list_fields: Iterable[str], bool_fields: Iterable[str] = ()) -> dict:
    result: dict[str, object] = dict(row)
    for field in list_fields:
        result[field] = _json_list(row.get(field))
    for field in bool_fields:
        result[field] = _bool(row.get(field))
    return result


def _selection_match(summary: dict[str, str], policy: str) -> bool:
    if policy == "all":
        return True
    if policy == "unknown":
        return summary.get("observed_management") == "unknown"
    if policy == "review_required":
        return _bool(summary.get("review_required"))
    if policy == "ambiguous":
        return (
            summary.get("observed_management") != "surgery"
            or summary.get("management_confidence") != "high"
            or int(summary.get("n_surgery_events") or 0) > 1
            or summary.get("surgery_event_count_status") != "exact"
        )
    raise ValueError(f"Unsupported selection policy: {policy}")


def _evidence_priority(row: dict[str, str], primary_ids: set[str]) -> tuple:
    assertion_priority = {
        "completed": 8,
        "cancelled_or_declined": 7,
        "conservative": 6,
        "intended": 5,
        "unrelated_completed": 4,
        "diagnostic_completed": 3,
    }
    strength_priority = {"high": 3, "medium": 2, "low": 1}
    return (
        row.get("evidence_id") in primary_ids,
        assertion_priority.get(row.get("assertion", ""), 0),
        strength_priority.get(row.get("strength", ""), 0),
        bool(row.get("evidence_date")),
        row.get("evidence_date", ""),
        row.get("evidence_id", ""),
    )


def _section_priority(section: dict, evidence_rows: list[dict[str, str]], primary_ids: set[str]) -> tuple:
    text = section.get("text", "")
    subtype_priority = {
        "surgery_record": 8,
        "postop_progress": 7,
        "preoperative_discussion": 6,
        "treatment_procedure_consent": 5,
        "condition_communication": 4,
    }
    evidence_score = sum(2 if row.get("evidence_id") in primary_ids else 1 for row in evidence_rows)
    return (
        any(row.get("evidence_id") in primary_ids for row in evidence_rows),
        evidence_score,
        subtype_priority.get(section.get("section_subtype", ""), 0),
        bool(MANAGEMENT_CUE_RE.search(text)),
        bool(AAOCA_ANCHOR_RE.search(text)),
        bool(section.get("section_date")),
        section.get("section_date", ""),
        section.get("section_id", ""),
    )


def _window(start: int, end: int, text_length: int, before: int = 700, after: int = 1100) -> tuple[int, int]:
    return max(0, start - before), min(text_length, end + after)


def _passages_for_section(
    section: dict,
    evidence_rows: list[dict[str, str]],
    *,
    max_characters: int,
) -> list[dict]:
    text = section.get("text", "")
    if not text or max_characters <= 0:
        return []
    candidates: list[tuple[int, int, int]] = []
    for row in evidence_rows:
        try:
            start, end = int(row.get("char_start") or 0), int(row.get("char_end") or 0)
        except ValueError:
            continue
        left, right = _window(start, end, len(text), 250, 350)
        candidates.append((100, left, right))
    for match in MANAGEMENT_CUE_RE.finditer(text):
        left, right = _window(match.start(), match.end(), len(text))
        candidates.append((60, left, right))
    for match in AAOCA_ANCHOR_RE.finditer(text):
        left, right = _window(match.start(), match.end(), len(text))
        candidates.append((40, left, right))
    if not candidates:
        candidates.append((1, 0, min(len(text), max_characters)))

    selected: list[tuple[int, int]] = []
    used = 0
    for _, start, end in sorted(candidates, key=lambda item: (-item[0], item[1], item[2])):
        if any(start >= old_start and end <= old_end for old_start, old_end in selected):
            continue
        remaining = max_characters - used
        if remaining <= 0:
            break
        if end - start > remaining:
            end = start + remaining
        if end <= start:
            continue
        selected.append((start, end))
        used += end - start

    # Merge overlaps after priority-based selection without expanding the
    # character budget.  This keeps passage IDs stable and removes duplicate
    # text that would otherwise waste model context.
    merged: list[list[int]] = []
    for start, end in sorted(selected):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    passages = []
    for start, end in merged:
        passage_id = _stable_id("pass", section.get("section_id", ""), start, end, text[start:end])
        passages.append(
            {
                "passage_id": passage_id,
                "document_id": section.get("document_id", ""),
                "section_id": section.get("section_id", ""),
                "section_type": section.get("section_type", ""),
                "section_subtype": section.get("section_subtype", ""),
                "section_date": section.get("section_date", ""),
                "page_start": section.get("page_start", ""),
                "page_end": section.get("page_end", ""),
                "text_source": section.get("text_source", ""),
                "date_requires_review": bool(section.get("date_requires_review")),
                "text_path": section.get("text_path", ""),
                "text_reference": section.get("text_reference", ""),
                "section_char_start": start,
                "section_char_end": end,
                "text": text[start:end],
            }
        )
    return passages


def _request_evidence(row: dict[str, str]) -> dict:
    return _decode_row(
        row,
        ["procedure_types", "date_candidates", "flags"],
        ["counts_as_aaoca_surgery", "date_requires_review"],
    )


def _request_event(row: dict[str, str]) -> dict:
    return _decode_row(
        row,
        [
            "procedure_types",
            "procedure_names",
            "supporting_evidence_ids",
            "source_document_ids",
            "source_section_ids",
            "conflict_flags",
        ],
        ["formal_surgery_record_present", "postoperative_evidence_present", "historical_only"],
    )


def _request_summary(row: dict[str, str]) -> dict:
    return _decode_row(
        row,
        [
            "surgery_dates",
            "surgery_date_precisions",
            "surgery_event_ids",
            "procedure_types",
            "procedure_names",
            "review_reasons",
        ],
        [
            "has_completed_surgery_evidence",
            "has_surgical_intent_evidence",
            "has_cancelled_or_declined_evidence",
            "has_conservative_evidence",
            "has_diagnostic_procedure_evidence",
            "has_unrelated_surgery_evidence",
            "review_required",
        ],
    )


def _request_package_readme() -> str:
    return """# AAOCA management LLM request package

This directory contains clinical excerpts and must remain local and restricted.
Preparing it does not call a model. `run_metadata.json` must say
`llm_invoked=false` and `network_processing=false`.

- `requests.jsonl`: provider-neutral one-patient request objects.
- `request_manifest.csv`: selection and explicit truncation receipt.
- `request_schema.json` / `response_schema.json`: versioned contracts.
- `prompt_template.md`: shared task semantics.
- `run_metadata.json`: source hashes, context limits and counts.

An adapter implementing `StructuredManagementLLMClient` may later receive a
request and response schema. Do not use an external endpoint without separate
data-owner approval. Validate all returned responses before reconciliation.
"""


def prepare_llm_request_package(
    management_root: Path,
    run_root: Path,
    relevance_root: Path,
    output: Path,
    *,
    selection_policy: str = "ambiguous",
    max_sections_per_patient: int = 24,
    max_evidence_rows_per_patient: int = 120,
    max_characters_per_section: int = 8000,
    max_passage_characters_per_patient: int = 80000,
    instructions: str = PROMPT_TEMPLATE,
    prompt_version: str = PROMPT_VERSION,
) -> dict:
    """Create local JSONL requests without invoking any model."""

    if min(
        max_sections_per_patient,
        max_evidence_rows_per_patient,
        max_characters_per_section,
        max_passage_characters_per_patient,
    ) <= 0:
        raise ValueError("All LLM context limits must be positive")
    if not instructions.strip() or not prompt_version.strip():
        raise ValueError("LLM instructions and prompt_version must be nonempty")
    management_root = management_root.resolve()
    run_root = run_root.resolve()
    relevance_root = relevance_root.resolve()
    output = output.resolve()
    validation = validate_management_package(management_root, run_root, relevance_root)
    if validation["validation_status"] != "passed":
        raise ValueError(f"Management package must validate before LLM preparation: {validation['errors'][:3]}")

    summaries = _read_csv(management_root / "management_summary.csv")
    evidence = _read_csv(management_root / "management_evidence.csv")
    events = _read_csv(management_root / "surgery_events.csv")
    selected_summaries = [row for row in summaries if _selection_match(row, selection_policy)]
    selected_ids = {row["patient_id"] for row in selected_summaries}
    sections = load_sections(run_root, selected_ids)

    evidence_by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    events_by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    sections_by_patient: dict[str, list[dict]] = defaultdict(list)
    for row in evidence:
        if row["patient_id"] in selected_ids:
            evidence_by_patient[row["patient_id"]].append(row)
    for row in events:
        if row["patient_id"] in selected_ids:
            events_by_patient[row["patient_id"]].append(row)
    for section in sections:
        sections_by_patient[section["patient_id"]].append(section)

    requests: list[dict] = []
    manifest: list[dict] = []
    for summary in sorted(selected_summaries, key=lambda row: row["patient_id"]):
        patient_id = summary["patient_id"]
        patient_events = events_by_patient[patient_id]
        primary_ids = {summary.get("primary_evidence_id", "")}
        primary_ids.update(event.get("primary_evidence_id", "") for event in patient_events)
        primary_ids.discard("")

        available_evidence = evidence_by_patient[patient_id]
        selected_evidence = sorted(
            available_evidence,
            key=lambda row: _evidence_priority(row, primary_ids),
            reverse=True,
        )[:max_evidence_rows_per_patient]
        selected_evidence_by_section: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in selected_evidence:
            selected_evidence_by_section[row["section_id"]].append(row)

        available_sections = sections_by_patient[patient_id]
        ranked_sections = sorted(
            available_sections,
            key=lambda section: _section_priority(
                section,
                selected_evidence_by_section.get(section["section_id"], []),
                primary_ids,
            ),
            reverse=True,
        )
        selected_sections = ranked_sections[:max_sections_per_patient]
        passages: list[dict] = []
        remaining = max_passage_characters_per_patient
        included_section_ids: list[str] = []
        for section in selected_sections:
            if remaining <= 0:
                break
            section_budget = min(max_characters_per_section, remaining)
            section_passages = _passages_for_section(
                section,
                selected_evidence_by_section.get(section["section_id"], []),
                max_characters=section_budget,
            )
            if not section_passages:
                continue
            passages.extend(section_passages)
            included_section_ids.append(section["section_id"])
            remaining -= sum(len(item["text"]) for item in section_passages)

        context_truncated = (
            len(selected_evidence) < len(available_evidence)
            or len(included_section_ids) < len(available_sections)
            or any(
                sum(len(item["text"]) for item in passages if item["section_id"] == section["section_id"])
                < len(section.get("text", ""))
                for section in selected_sections
                if section["section_id"] in set(included_section_ids)
            )
        )
        request_id = _stable_id(
            "llmreq",
            LLM_INTERFACE_VERSION,
            prompt_version,
            hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
            patient_id,
            sha256_file(management_root / "run_metadata.json"),
            selection_policy,
        )
        request = {
            "interface_version": LLM_INTERFACE_VERSION,
            "prompt_version": prompt_version,
            "request_id": request_id,
            "patient_id": patient_id,
            "instructions": instructions,
            "case": {
                "deterministic_summary": _request_summary(summary),
                "deterministic_surgery_events": [_request_event(row) for row in patient_events],
                "deterministic_evidence": [_request_evidence(row) for row in selected_evidence],
                "source_passages": passages,
                "context_receipt": {
                    "selection_policy": selection_policy,
                    "available_evidence_rows": len(available_evidence),
                    "included_evidence_rows": len(selected_evidence),
                    "omitted_evidence_rows": len(available_evidence) - len(selected_evidence),
                    "available_sections": len(available_sections),
                    "included_sections": len(included_section_ids),
                    "included_section_ids": included_section_ids,
                    "included_passage_characters": sum(len(item["text"]) for item in passages),
                    "context_truncated": context_truncated,
                },
            },
            "response_schema_id": RESPONSE_SCHEMA["$id"],
        }
        requests.append(request)
        manifest.append(
            {
                "request_id": request_id,
                "patient_id": patient_id,
                "selection_policy": selection_policy,
                "deterministic_management": summary["observed_management"],
                "deterministic_actual_aaoca_surgery": summary["actual_aaoca_surgery"],
                "n_available_evidence_rows": len(available_evidence),
                "n_included_evidence_rows": len(selected_evidence),
                "n_omitted_evidence_rows": len(available_evidence) - len(selected_evidence),
                "n_available_sections": len(available_sections),
                "n_included_sections": len(included_section_ids),
                "n_passages": len(passages),
                "included_passage_characters": sum(len(item["text"]) for item in passages),
                "context_truncated": context_truncated,
            }
        )

    _write_jsonl(output / "requests.jsonl", requests)
    write_csv(output / "request_manifest.csv", manifest, REQUEST_MANIFEST_FIELDS)
    write_json(output / "request_schema.json", REQUEST_SCHEMA)
    write_json(output / "response_schema.json", RESPONSE_SCHEMA)
    write_text(output / "prompt_template.md", instructions)
    write_text(output / "README.md", _request_package_readme())
    source_hashes = {
        "management_metadata": sha256_file(management_root / "run_metadata.json"),
        "management_summary": sha256_file(management_root / "management_summary.csv"),
        "management_evidence": sha256_file(management_root / "management_evidence.csv"),
        "surgery_events": sha256_file(management_root / "surgery_events.csv"),
        "run_section_index": sha256_file(run_root / "section_index.csv"),
        "relevance_cases": sha256_file(relevance_root / "exception_cases.csv"),
    }
    metadata = {
        "interface_version": LLM_INTERFACE_VERSION,
        "prompt_version": prompt_version,
        "prompt_sha256": hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
        "status": "requests_prepared",
        "selection_policy": selection_policy,
        "contains_clinical_excerpts": True,
        "network_processing": False,
        "llm_invoked": False,
        "endpoint_configured": False,
        "source_management": str(management_root),
        "source_run": str(run_root),
        "source_relevance_review": str(relevance_root),
        "context_limits": {
            "max_sections_per_patient": max_sections_per_patient,
            "max_evidence_rows_per_patient": max_evidence_rows_per_patient,
            "max_characters_per_section": max_characters_per_section,
            "max_passage_characters_per_patient": max_passage_characters_per_patient,
        },
        "counts": {
            "requests": len(requests),
            "deterministic_statuses": dict(Counter(row["observed_management"] for row in selected_summaries)),
            "included_evidence_rows": sum(row["n_included_evidence_rows"] for row in manifest),
            "omitted_evidence_rows": sum(row["n_omitted_evidence_rows"] for row in manifest),
            "source_passages": sum(row["n_passages"] for row in manifest),
            "passage_characters": sum(row["included_passage_characters"] for row in manifest),
            "requests_with_truncated_context": sum(_bool(row["context_truncated"]) for row in manifest),
        },
        "source_hashes": source_hashes,
        "code_sha256": sha256_file(Path(__file__)),
    }
    write_json(output / "run_metadata.json", metadata)
    package_validation = validate_llm_request_package(output, management_root, run_root)
    if package_validation["validation_status"] != "passed":
        raise ValueError(f"Generated LLM request package failed validation: {package_validation['errors'][:3]}")
    return {**metadata, "validation": package_validation}


def validate_llm_request_package(
    request_root: Path,
    management_root: Path | None = None,
    run_root: Path | None = None,
) -> dict:
    """Validate request identity, receipts, hashes and exact source passages."""

    request_root = request_root.resolve()
    errors: list[dict] = []
    warnings: list[dict] = []
    required = {
        "requests": request_root / "requests.jsonl",
        "manifest": request_root / "request_manifest.csv",
        "request_schema": request_root / "request_schema.json",
        "response_schema": request_root / "response_schema.json",
        "prompt": request_root / "prompt_template.md",
        "metadata": request_root / "run_metadata.json",
    }
    for name, path in required.items():
        if not path.is_file():
            errors.append({"code": "missing_artifact", "artifact": name, "path": str(path)})
    if errors:
        return {
            "validation_status": "failed",
            "error_count": len(errors),
            "warning_count": 0,
            "errors": errors,
            "warnings": [],
        }
    try:
        requests = _read_jsonl(required["requests"])
        manifest = _read_csv(required["manifest"])
        metadata = json.loads(required["metadata"].read_text(encoding="utf-8"))
        request_schema = json.loads(required["request_schema"].read_text(encoding="utf-8"))
        response_schema = json.loads(required["response_schema"].read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        errors.append({"code": "invalid_package_json", "detail": str(exc)})
        return {
            "validation_status": "failed",
            "error_count": len(errors),
            "warning_count": 0,
            "errors": errors,
            "warnings": [],
        }

    if request_schema != REQUEST_SCHEMA or response_schema != RESPONSE_SCHEMA:
        errors.append({"code": "interface_schema_mismatch"})
    prompt_text = required["prompt"].read_text(encoding="utf-8")
    request_ids = [request.get("request_id", "") for request in requests]
    patient_ids = [request.get("patient_id", "") for request in requests]
    if "" in request_ids or len(request_ids) != len(set(request_ids)):
        errors.append({"code": "missing_or_duplicate_request_id"})
    if "" in patient_ids or len(patient_ids) != len(set(patient_ids)):
        errors.append({"code": "missing_or_duplicate_request_patient"})
    manifest_ids = [row.get("request_id", "") for row in manifest]
    if set(manifest_ids) != set(request_ids) or len(manifest_ids) != len(request_ids):
        errors.append({"code": "request_manifest_mismatch"})

    passage_ids: set[str] = set()
    for request in requests:
        request_id = request.get("request_id", "")
        patient_id = request.get("patient_id", "")
        if request.get("interface_version") != LLM_INTERFACE_VERSION:
            errors.append({"code": "request_interface_version_invalid", "request_id": request_id})
        if request.get("prompt_version") != metadata.get("prompt_version") or request.get("instructions") != prompt_text:
            errors.append({"code": "request_prompt_invalid", "request_id": request_id})
        if request.get("response_schema_id") != RESPONSE_SCHEMA["$id"]:
            errors.append({"code": "request_response_schema_invalid", "request_id": request_id})
        case = request.get("case")
        if not isinstance(case, dict):
            errors.append({"code": "request_case_invalid", "request_id": request_id})
            continue
        summary = case.get("deterministic_summary")
        evidence = case.get("deterministic_evidence")
        events = case.get("deterministic_surgery_events")
        passages = case.get("source_passages")
        receipt = case.get("context_receipt")
        if not isinstance(summary, dict) or summary.get("patient_id") != patient_id:
            errors.append({"code": "request_summary_patient_mismatch", "request_id": request_id})
        if not isinstance(evidence, list) or not isinstance(events, list) or not isinstance(passages, list):
            errors.append({"code": "request_context_collection_invalid", "request_id": request_id})
            continue
        evidence_ids = [row.get("evidence_id", "") for row in evidence if isinstance(row, dict)]
        if len(evidence_ids) != len(set(evidence_ids)) or "" in evidence_ids:
            errors.append({"code": "request_evidence_id_invalid", "request_id": request_id})
        local_passage_ids = []
        for passage in passages:
            if not isinstance(passage, dict):
                errors.append({"code": "request_passage_invalid", "request_id": request_id})
                continue
            passage_id = passage.get("passage_id", "")
            local_passage_ids.append(passage_id)
            if not passage_id or passage_id in passage_ids:
                errors.append({"code": "duplicate_or_missing_passage_id", "request_id": request_id})
            passage_ids.add(passage_id)
            start, end = passage.get("section_char_start"), passage.get("section_char_end")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
                errors.append({"code": "request_passage_span_invalid", "request_id": request_id, "passage_id": passage_id})
            elif len(passage.get("text", "")) != end - start:
                errors.append({"code": "request_passage_length_mismatch", "request_id": request_id, "passage_id": passage_id})
        if len(local_passage_ids) != len(set(local_passage_ids)):
            errors.append({"code": "duplicate_passage_within_request", "request_id": request_id})
        if not isinstance(receipt, dict):
            errors.append({"code": "request_context_receipt_invalid", "request_id": request_id})
        else:
            if receipt.get("included_evidence_rows") != len(evidence):
                errors.append({"code": "request_evidence_receipt_mismatch", "request_id": request_id})
            if receipt.get("included_passage_characters") != sum(len(row.get("text", "")) for row in passages):
                errors.append({"code": "request_passage_receipt_mismatch", "request_id": request_id})

    if (
        metadata.get("interface_version") != LLM_INTERFACE_VERSION
        or not isinstance(metadata.get("prompt_version"), str)
        or not metadata.get("prompt_version", "").strip()
        or metadata.get("prompt_sha256") != hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    ):
        errors.append({"code": "request_metadata_version_invalid"})
    if metadata.get("llm_invoked") is not False or metadata.get("network_processing") is not False:
        errors.append({"code": "request_metadata_false_invocation_receipt_invalid"})
    counts = metadata.get("counts", {})
    if counts.get("requests") != len(requests):
        errors.append({"code": "request_metadata_count_mismatch"})

    management_evidence_by_id: dict[str, dict[str, str]] = {}
    if management_root:
        management_root = management_root.resolve()
        source_hashes = metadata.get("source_hashes", {})
        expected_hashes = {
            "management_metadata": sha256_file(management_root / "run_metadata.json"),
            "management_summary": sha256_file(management_root / "management_summary.csv"),
            "management_evidence": sha256_file(management_root / "management_evidence.csv"),
            "surgery_events": sha256_file(management_root / "surgery_events.csv"),
        }
        for key, expected in expected_hashes.items():
            if source_hashes.get(key) != expected:
                errors.append({"code": "request_source_hash_mismatch", "source": key})
        management_evidence_by_id = {
            row["evidence_id"]: row for row in _read_csv(management_root / "management_evidence.csv")
        }
        for request in requests:
            patient_id = request["patient_id"]
            for row in request.get("case", {}).get("deterministic_evidence", []):
                source = management_evidence_by_id.get(row.get("evidence_id", ""))
                if not source or source["patient_id"] != patient_id:
                    errors.append(
                        {
                            "code": "request_management_evidence_invalid",
                            "request_id": request["request_id"],
                            "evidence_id": row.get("evidence_id", ""),
                        }
                    )

    if run_root:
        run_root = run_root.resolve()
        if metadata.get("source_hashes", {}).get("run_section_index") != sha256_file(run_root / "section_index.csv"):
            errors.append({"code": "request_source_hash_mismatch", "source": "run_section_index"})
        source_sections = {
            row["section_id"]: row for row in load_sections(run_root, set(patient_ids))
        }
        for request in requests:
            for passage in request.get("case", {}).get("source_passages", []):
                source = source_sections.get(passage.get("section_id", ""))
                if not source or source.get("patient_id") != request["patient_id"]:
                    errors.append(
                        {
                            "code": "request_passage_section_invalid",
                            "request_id": request["request_id"],
                            "passage_id": passage.get("passage_id", ""),
                        }
                    )
                    continue
                start, end = passage["section_char_start"], passage["section_char_end"]
                if source.get("text", "")[start:end] != passage.get("text", ""):
                    errors.append(
                        {
                            "code": "request_passage_source_mismatch",
                            "request_id": request["request_id"],
                            "passage_id": passage.get("passage_id", ""),
                        }
                    )

    return {
        "validation_status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "requests": len(requests),
        "patients": len(set(patient_ids)),
        "passages": len(passage_ids),
        "errors": errors,
        "warnings": warnings,
    }


def _response_error(errors: list[dict], code: str, response: Mapping[str, object], **details: object) -> None:
    errors.append(
        {
            "code": code,
            "request_id": str(response.get("request_id", "")),
            "patient_id": str(response.get("patient_id", "")),
            **details,
        }
    )


def _valid_event_date(value: str, precision: str) -> bool:
    if precision == "unknown":
        return value == ""
    if precision == "year":
        return bool(re.fullmatch(r"(?:19|20)\d{2}", value))
    if precision == "month":
        match = re.fullmatch(r"((?:19|20)\d{2})-(\d{2})", value)
        return bool(match and 1 <= int(match.group(2)) <= 12)
    if precision == "day":
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    return False


def _validate_citation(
    citation: object,
    passages: dict[str, dict],
    response: Mapping[str, object],
    errors: list[dict],
) -> bool:
    if not isinstance(citation, dict):
        _response_error(errors, "citation_not_object", response)
        return False
    required = {"passage_id", "quote_start", "quote_end", "quote", "purpose"}
    if set(citation) != required:
        _response_error(errors, "citation_fields_invalid", response)
        return False
    passage = passages.get(citation.get("passage_id", ""))
    if not passage:
        _response_error(errors, "citation_passage_not_allowed", response, passage_id=citation.get("passage_id", ""))
        return False
    start, end = citation.get("quote_start"), citation.get("quote_end")
    if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
        _response_error(errors, "citation_offsets_invalid", response, passage_id=citation.get("passage_id", ""))
        return False
    text = passage.get("text", "")
    if start < 0 or end <= start or end > len(text) or text[start:end] != citation.get("quote"):
        _response_error(errors, "citation_quote_mismatch", response, passage_id=citation.get("passage_id", ""))
        return False
    if not isinstance(citation.get("purpose"), str) or not citation.get("purpose", "").strip():
        _response_error(errors, "citation_purpose_invalid", response, passage_id=citation.get("passage_id", ""))
        return False
    return True


def validate_llm_responses(
    request_root: Path,
    responses_path: Path,
    *,
    require_complete: bool = False,
) -> dict:
    """Validate structured responses without trusting provider output."""

    request_root = request_root.resolve()
    responses_path = responses_path.resolve()
    errors: list[dict] = []
    warnings: list[dict] = []
    if not responses_path.is_file():
        return {
            "validation_status": "failed",
            "error_count": 1,
            "warning_count": 0,
            "errors": [{"code": "responses_missing", "path": str(responses_path)}],
            "warnings": [],
        }
    try:
        requests = _read_jsonl(request_root / "requests.jsonl")
        responses = _read_jsonl(responses_path)
    except ValueError as exc:
        return {
            "validation_status": "failed",
            "error_count": 1,
            "warning_count": 0,
            "errors": [{"code": "invalid_jsonl", "detail": str(exc)}],
            "warnings": [],
        }
    request_by_id = {row["request_id"]: row for row in requests}
    response_ids = [str(row.get("request_id", "")) for row in responses]
    if "" in response_ids or len(response_ids) != len(set(response_ids)):
        errors.append({"code": "missing_or_duplicate_response_request_id"})
    unknown_ids = set(response_ids) - set(request_by_id)
    for request_id in sorted(unknown_ids):
        errors.append({"code": "response_request_not_found", "request_id": request_id})
    if require_complete:
        missing = set(request_by_id) - set(response_ids)
        for request_id in sorted(missing):
            errors.append({"code": "response_missing", "request_id": request_id})

    response_statuses: Counter[str] = Counter()
    for response in responses:
        request = request_by_id.get(str(response.get("request_id", "")))
        if not request:
            continue
        required_response = {
            "interface_version",
            "request_id",
            "patient_id",
            "model_receipt",
            "assessment",
        }
        if set(response) != required_response:
            _response_error(errors, "response_fields_invalid", response)
        if response.get("interface_version") != LLM_INTERFACE_VERSION:
            _response_error(errors, "response_interface_version_invalid", response)
        if response.get("patient_id") != request.get("patient_id"):
            _response_error(errors, "response_patient_mismatch", response)
        receipt = response.get("model_receipt")
        if (
            not isinstance(receipt, dict)
            or not isinstance(receipt.get("provider"), str)
            or not receipt.get("provider", "").strip()
            or not isinstance(receipt.get("model"), str)
            or not receipt.get("model", "").strip()
        ):
            _response_error(errors, "model_receipt_invalid", response)
        assessment = response.get("assessment")
        if not isinstance(assessment, dict):
            _response_error(errors, "assessment_not_object", response)
            continue
        required_assessment = {
            "observed_management",
            "actual_aaoca_surgery",
            "confidence",
            "rationale",
            "deterministic_evidence_ids",
            "citations",
            "surgery_events",
            "uncertainties",
            "requires_human_review",
        }
        if set(assessment) != required_assessment:
            _response_error(errors, "assessment_fields_invalid", response)
            continue
        management = assessment.get("observed_management")
        actual = assessment.get("actual_aaoca_surgery")
        response_statuses[str(management)] += 1
        if management not in MANAGEMENT_VALUES:
            _response_error(errors, "response_management_invalid", response)
        if actual not in SURGERY_STATUS_VALUES:
            _response_error(errors, "response_actual_surgery_invalid", response)
        if assessment.get("confidence") not in {"high", "medium", "low"}:
            _response_error(errors, "response_confidence_invalid", response)
        if not isinstance(assessment.get("rationale"), str) or not assessment.get("rationale", "").strip():
            _response_error(errors, "response_rationale_invalid", response)
        if not isinstance(assessment.get("uncertainties"), list) or not all(
            isinstance(value, str) for value in assessment.get("uncertainties", [])
        ):
            _response_error(errors, "response_uncertainties_invalid", response)
        if not isinstance(assessment.get("requires_human_review"), bool):
            _response_error(errors, "response_review_flag_invalid", response)

        request_evidence = {
            row["evidence_id"]: row for row in request["case"].get("deterministic_evidence", [])
        }
        request_passages = {
            row["passage_id"]: row for row in request["case"].get("source_passages", [])
        }
        top_ids = assessment.get("deterministic_evidence_ids")
        if not isinstance(top_ids, list) or not all(isinstance(value, str) for value in top_ids):
            _response_error(errors, "response_evidence_ids_invalid", response)
            top_ids = []
        if len(top_ids) != len(set(top_ids)):
            _response_error(errors, "response_evidence_ids_duplicate", response)
        for evidence_id in top_ids:
            if evidence_id not in request_evidence:
                _response_error(errors, "response_evidence_id_not_allowed", response, evidence_id=evidence_id)

        citations = assessment.get("citations")
        if not isinstance(citations, list):
            _response_error(errors, "response_citations_invalid", response)
            citations = []
        for citation in citations:
            _validate_citation(citation, request_passages, response, errors)

        surgery_events = assessment.get("surgery_events")
        if not isinstance(surgery_events, list):
            _response_error(errors, "response_surgery_events_invalid", response)
            surgery_events = []
        completed_related = []
        all_event_ids: list[str] = []
        for index, event in enumerate(surgery_events):
            if not isinstance(event, dict):
                _response_error(errors, "response_event_not_object", response, event_index=index)
                continue
            required_event = {
                "event_label",
                "occurrence",
                "aaoca_relation",
                "procedure_name",
                "procedure_types",
                "date",
                "date_precision",
                "deterministic_evidence_ids",
                "citations",
            }
            if set(event) != required_event:
                _response_error(errors, "response_event_fields_invalid", response, event_index=index)
                continue
            if event.get("occurrence") not in {"completed", "intended", "cancelled_or_declined"}:
                _response_error(errors, "response_event_occurrence_invalid", response, event_index=index)
            if event.get("aaoca_relation") not in {"related", "unrelated", "uncertain"}:
                _response_error(errors, "response_event_relation_invalid", response, event_index=index)
            if not isinstance(event.get("event_label"), str) or not event.get("event_label", "").strip():
                _response_error(errors, "response_event_label_invalid", response, event_index=index)
            if not isinstance(event.get("procedure_name"), str) or not isinstance(event.get("procedure_types"), list):
                _response_error(errors, "response_event_procedure_invalid", response, event_index=index)
            elif not all(isinstance(value, str) for value in event.get("procedure_types", [])):
                _response_error(errors, "response_event_procedure_types_invalid", response, event_index=index)
            if not _valid_event_date(str(event.get("date", "")), str(event.get("date_precision", ""))):
                _response_error(errors, "response_event_date_invalid", response, event_index=index)
            event_ids = event.get("deterministic_evidence_ids")
            if not isinstance(event_ids, list) or not all(isinstance(value, str) for value in event_ids):
                _response_error(errors, "response_event_evidence_ids_invalid", response, event_index=index)
                event_ids = []
            if len(event_ids) != len(set(event_ids)):
                _response_error(errors, "response_event_evidence_ids_duplicate", response, event_index=index)
            for evidence_id in event_ids:
                if evidence_id not in request_evidence:
                    _response_error(
                        errors,
                        "response_event_evidence_id_not_allowed",
                        response,
                        event_index=index,
                        evidence_id=evidence_id,
                    )
            all_event_ids.extend(event_ids)
            event_citations = event.get("citations")
            if not isinstance(event_citations, list):
                _response_error(errors, "response_event_citations_invalid", response, event_index=index)
                event_citations = []
            for citation in event_citations:
                _validate_citation(citation, request_passages, response, errors)
            if not event_ids and not event_citations:
                _response_error(errors, "response_event_without_support", response, event_index=index)
            if event.get("occurrence") == "completed" and event.get("aaoca_relation") == "related":
                completed_related.append(event)

        if (management == "surgery") != (actual == "yes"):
            _response_error(errors, "response_management_actual_mismatch", response)
        if management == "surgery" and not completed_related:
            _response_error(errors, "response_surgery_without_completed_related_event", response)
        if management == "intended_surgery" and not any(
            event.get("aaoca_relation") == "related"
            and event.get("occurrence") in {"intended", "cancelled_or_declined"}
            for event in surgery_events
            if isinstance(event, dict)
        ):
            _response_error(errors, "response_intent_without_related_event", response)
        if management == "conservative" and not (top_ids or citations):
            _response_error(errors, "response_conservative_without_support", response)
        if actual == "no" and management != "conservative":
            _response_error(errors, "response_actual_no_without_conservative_state", response)

        cited_ids = set(top_ids) | set(all_event_ids)
        verified_completed = any(
            row.get("assertion") == "completed" and _bool(row.get("counts_as_aaoca_surgery"))
            for evidence_id, row in request_evidence.items()
            if evidence_id in cited_ids
        )
        verified_explicit_no = any(
            row.get("assertion") == "conservative" and row.get("strength") == "high"
            for evidence_id, row in request_evidence.items()
            if evidence_id in cited_ids
        )
        verified_conservative = any(
            row.get("assertion") == "conservative"
            for evidence_id, row in request_evidence.items()
            if evidence_id in cited_ids
        )
        verified_intent = any(
            row.get("assertion") in {"intended", "cancelled_or_declined"}
            and row.get("event_kind") != "diagnostic_procedure"
            for evidence_id, row in request_evidence.items()
            if evidence_id in cited_ids
        )
        if management == "surgery" and not verified_completed and assessment.get("requires_human_review") is not True:
            _response_error(errors, "new_surgery_claim_requires_human_review", response)
        if management == "intended_surgery" and not verified_intent and assessment.get("requires_human_review") is not True:
            _response_error(errors, "new_intent_claim_requires_human_review", response)
        if management == "conservative" and not verified_conservative and assessment.get("requires_human_review") is not True:
            _response_error(errors, "new_conservative_claim_requires_human_review", response)
        if actual == "no" and not verified_explicit_no and assessment.get("requires_human_review") is not True:
            _response_error(errors, "new_actual_no_claim_requires_human_review", response)

        deterministic = request["case"].get("deterministic_summary", {})
        disagreement = (
            management != deterministic.get("observed_management")
            or actual != deterministic.get("actual_aaoca_surgery")
        )
        if disagreement and assessment.get("requires_human_review") is not True:
            _response_error(errors, "llm_disagreement_requires_human_review", response)

    return {
        "validation_status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "requests": len(requests),
        "responses": len(responses),
        "complete": len(responses) == len(requests) and not (set(request_by_id) - set(response_ids)),
        "response_statuses": dict(response_statuses),
        "errors": errors,
        "warnings": warnings,
    }


def execute_llm_requests(
    request_root: Path,
    responses_path: Path,
    client: StructuredManagementLLMClient,
    *,
    limit: int | None = None,
) -> dict:
    """Execute prepared requests through an injected adapter.

    There is intentionally no CLI endpoint implementation.  A future approved
    adapter can call this function without changing request preparation,
    validation or reconciliation.
    """

    request_root = request_root.resolve()
    requests = _read_jsonl(request_root / "requests.jsonl")
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        requests = requests[:limit]
    responses: list[Mapping[str, object]] = []
    for request in requests:
        response = client.complete(request, RESPONSE_SCHEMA)
        if not isinstance(response, Mapping):
            raise TypeError("StructuredManagementLLMClient.complete must return a mapping")
        responses.append(response)
    _write_jsonl(responses_path.resolve(), responses)
    return validate_llm_responses(
        request_root,
        responses_path,
        require_complete=limit is None,
    )


def reconcile_llm_responses(
    management_root: Path,
    request_root: Path,
    responses_path: Path,
    output: Path,
) -> dict:
    """Write a sidecar comparison; deterministic patient rows remain unchanged."""

    management_root = management_root.resolve()
    request_root = request_root.resolve()
    responses_path = responses_path.resolve()
    output = output.resolve()
    response_validation = validate_llm_responses(request_root, responses_path)
    if response_validation["validation_status"] != "passed":
        raise ValueError(f"LLM responses failed validation: {response_validation['errors'][:3]}")

    summaries = _read_csv(management_root / "management_summary.csv")
    responses = _read_jsonl(responses_path)
    response_by_patient = {row["patient_id"]: row for row in responses}
    hybrid_rows: list[dict] = []
    for summary in summaries:
        patient_id = summary["patient_id"]
        response = response_by_patient.get(patient_id)
        deterministic_reasons = _json_list(summary.get("review_reasons"))
        if not response:
            hybrid_rows.append(
                {
                    "patient_id": patient_id,
                    "deterministic_management": summary["observed_management"],
                    "deterministic_actual_aaoca_surgery": summary["actual_aaoca_surgery"],
                    "deterministic_confidence": summary["management_confidence"],
                    "deterministic_review_required": _bool(summary["review_required"]),
                    "llm_response_present": False,
                    "llm_management": "",
                    "llm_actual_aaoca_surgery": "",
                    "llm_confidence": "",
                    "llm_requires_human_review": "",
                    "llm_deterministic_evidence_ids": [],
                    "llm_citation_count": 0,
                    "comparison": "no_response",
                    "recommended_management": summary["observed_management"],
                    "recommended_actual_aaoca_surgery": summary["actual_aaoca_surgery"],
                    "recommendation_rule": "deterministic_preserved_no_llm_response",
                    "review_required": _bool(summary["review_required"]),
                    "review_reasons": deterministic_reasons,
                }
            )
            continue
        assessment = response["assessment"]
        agrees = (
            assessment["observed_management"] == summary["observed_management"]
            and assessment["actual_aaoca_surgery"] == summary["actual_aaoca_surgery"]
        )
        comparison = "agreement" if agrees else "disagreement_review"
        reasons = list(deterministic_reasons)
        if not agrees:
            reasons.append("llm_deterministic_disagreement")
        if assessment["requires_human_review"]:
            reasons.append("llm_requests_human_review")
        all_citations = list(assessment["citations"])
        for event in assessment["surgery_events"]:
            all_citations.extend(event["citations"])
        hybrid_rows.append(
            {
                "patient_id": patient_id,
                "deterministic_management": summary["observed_management"],
                "deterministic_actual_aaoca_surgery": summary["actual_aaoca_surgery"],
                "deterministic_confidence": summary["management_confidence"],
                "deterministic_review_required": _bool(summary["review_required"]),
                "llm_response_present": True,
                "llm_management": assessment["observed_management"],
                "llm_actual_aaoca_surgery": assessment["actual_aaoca_surgery"],
                "llm_confidence": assessment["confidence"],
                "llm_requires_human_review": assessment["requires_human_review"],
                "llm_deterministic_evidence_ids": assessment["deterministic_evidence_ids"],
                "llm_citation_count": len(all_citations),
                "comparison": comparison,
                # v1 is intentionally sidecar-only.  Agreement can corroborate
                # a rule result; disagreement remains a candidate for review.
                "recommended_management": summary["observed_management"],
                "recommended_actual_aaoca_surgery": summary["actual_aaoca_surgery"],
                "recommendation_rule": (
                    "deterministic_llm_agreement" if agrees else "deterministic_preserved_pending_llm_disagreement_review"
                ),
                "review_required": _bool(summary["review_required"]) or not agrees or assessment["requires_human_review"],
                "review_reasons": list(dict.fromkeys(reasons)),
            }
        )

    write_csv(output / "hybrid_management_summary.csv", hybrid_rows, HYBRID_FIELDS)
    _write_jsonl(output / "llm_assessments.jsonl", responses)
    write_json(output / "response_validation.json", response_validation)
    metadata = {
        "interface_version": LLM_INTERFACE_VERSION,
        "method": "deterministic_with_llm_sidecar",
        "reconciliation_policy": "sidecar_only_no_silent_override_v1",
        "contains_clinical_excerpts": True,
        "source_management": str(management_root),
        "source_requests": str(request_root),
        "source_responses": str(responses_path),
        "counts": {
            "patients": len(hybrid_rows),
            "responses": len(responses),
            "agreements": sum(row["comparison"] == "agreement" for row in hybrid_rows),
            "disagreements_requiring_review": sum(row["comparison"] == "disagreement_review" for row in hybrid_rows),
            "patients_without_response": sum(row["comparison"] == "no_response" for row in hybrid_rows),
        },
        "source_hashes": {
            "management_summary": sha256_file(management_root / "management_summary.csv"),
            "request_metadata": sha256_file(request_root / "run_metadata.json"),
            "requests": sha256_file(request_root / "requests.jsonl"),
            "responses": sha256_file(responses_path),
        },
        "code_sha256": sha256_file(Path(__file__)),
    }
    write_json(output / "run_metadata.json", metadata)
    return {**metadata, "response_validation": response_validation}
