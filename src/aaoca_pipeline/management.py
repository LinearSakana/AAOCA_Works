"""Evidence-first AAOCA management and surgery extraction.

This module is intentionally downstream of a completed pipeline snapshot.  It
never changes source PDFs or the base ``data/derived`` artifacts.  The rules
separate an operation's clinical relation, assertion state and document role:
a surgery-record section can describe diagnostic catheterisation or an
unrelated operation, while a discharge summary can be the only surviving
proof of an earlier AAOCA operation.

The deterministic output is conservative by design.  ``surgery`` requires an
explicit AAOCA-relevant completed-procedure assertion; ``conservative``
requires an explicit non-operative decision; absence of an operation record is
never converted to ``conservative``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Protocol

from .io_utils import sha256_file, write_csv, write_json, write_text


RULESET_VERSION = "aaoca_management_rules_v1"
SCHEMA_VERSION = "aaoca_management_v1"

MANAGEMENT_VALUES = {"surgery", "intended_surgery", "conservative", "unknown"}
SURGERY_STATUS_VALUES = {"yes", "no", "unknown"}
ASSERTION_VALUES = {
    "completed",
    "intended",
    "cancelled_or_declined",
    "conservative",
    "diagnostic_completed",
    "unrelated_completed",
}

SELECTION_FIELDS = [
    "patient_id",
    "aaoca_judgment",
    "judgment_source",
    "review_status",
    "included_for_management",
    "exclusion_reason",
]

EVIDENCE_FIELDS = [
    "patient_id",
    "evidence_id",
    "rule_id",
    "assertion",
    "event_kind",
    "strength",
    "aaoca_relation",
    "counts_as_aaoca_surgery",
    "procedure_name_raw",
    "procedure_types",
    "evidence_date",
    "date_precision",
    "date_role",
    "date_status",
    "date_candidates",
    "document_id",
    "section_id",
    "section_type",
    "section_subtype",
    "section_date",
    "page_start",
    "page_end",
    "text_source",
    "date_requires_review",
    "parse_status",
    "source_pdf",
    "text_path",
    "text_reference",
    "char_start",
    "char_end",
    "evidence_text",
    "flags",
]

EVENT_FIELDS = [
    "patient_id",
    "surgery_event_id",
    "surgery_date",
    "surgery_date_precision",
    "date_status",
    "procedure_types",
    "procedure_names",
    "n_supporting_evidence",
    "primary_evidence_id",
    "supporting_evidence_ids",
    "formal_surgery_record_present",
    "postoperative_evidence_present",
    "historical_only",
    "relation_confidence",
    "source_document_ids",
    "source_section_ids",
    "primary_document_id",
    "primary_section_id",
    "primary_page_start",
    "primary_page_end",
    "primary_text_path",
    "primary_text_reference",
    "conflict_flags",
]

SUMMARY_FIELDS = [
    "patient_id",
    "aaoca_judgment",
    "aaoca_judgment_source",
    "observed_management",
    "actual_aaoca_surgery",
    "management_confidence",
    "management_rule",
    "n_surgery_events",
    "surgery_event_count_status",
    "first_surgery_date",
    "last_surgery_date",
    "surgery_dates",
    "surgery_date_precisions",
    "surgery_event_ids",
    "procedure_types",
    "procedure_names",
    "has_completed_surgery_evidence",
    "has_surgical_intent_evidence",
    "has_cancelled_or_declined_evidence",
    "has_conservative_evidence",
    "has_diagnostic_procedure_evidence",
    "has_unrelated_surgery_evidence",
    "primary_evidence_id",
    "primary_document_id",
    "primary_section_id",
    "primary_page_start",
    "primary_page_end",
    "primary_text_path",
    "primary_text_reference",
    "n_management_evidence_rows",
    "review_required",
    "review_reasons",
]

QC_FIELDS = [
    "patient_id",
    "observed_management",
    "issue_type",
    "severity",
    "evidence_ids",
    "detail",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json_list(value: str | list | None) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [part for part in str(value).split("|") if part]
    return parsed if isinstance(parsed, list) else []


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _stable_id(prefix: str, *values: object) -> str:
    payload = "\x1f".join(str(value) for value in values)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("开又", "开口").replace("开囗", "开口")


DATE_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2}|19\d{2})\s*[年./-]\s*"
    r"(?P<month>0?[1-9]|1[0-2])\s*[月./-]\s*"
    r"(?P<day>0?[1-9]|[12]\d|3[01])\s*日?(?!\d)"
)

MONTH_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2}|19\d{2})\s*[年./-]\s*"
    r"(?P<month>0?[1-9]|1[0-2])\s*月?(?!\s*[./-]\s*\d)(?!\d)"
)


def _iso_date(match: re.Match[str]) -> str:
    try:
        parsed = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return ""
    return parsed.isoformat()


def _dates_in(value: str) -> list[str]:
    return list(dict.fromkeys(day for match in DATE_RE.finditer(value or "") if (day := _iso_date(match))))


def _months_in(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            f"{int(match.group('year')):04d}-{int(match.group('month')):02d}"
            for match in MONTH_RE.finditer(value or "")
        )
    )


def resolve_aaoca_cohort(run_root: Path, relevance_root: Path) -> tuple[list[dict], dict]:
    """Resolve the review result without treating blank human fields as labels.

    The relevance deliverable is exception-only.  Under that explicit
    contract, patients omitted from ``exception_cases.csv`` are automatic
    ``yes`` cases.  A completed human label overrides the automatic exception
    judgment; incomplete human fields never do.
    """

    run_root = run_root.resolve()
    relevance_root = relevance_root.resolve()
    run_metadata_path = run_root / "run_metadata.json"
    manifest_path = run_root / "patient_manifest.csv"
    section_index_path = run_root / "section_index.csv"
    review_metadata_path = relevance_root / "run_metadata.json"
    cases_path = relevance_root / "exception_cases.csv"
    required = [run_metadata_path, manifest_path, section_index_path, review_metadata_path, cases_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError(f"Missing required source artifacts: {missing}")

    run_metadata = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    if run_metadata.get("status") != "complete":
        raise ValueError("Management extraction requires a completed pipeline snapshot")
    review_metadata = json.loads(review_metadata_path.read_text(encoding="utf-8"))
    if review_metadata.get("human_deliverable_scope") != "exception_patients_only":
        raise ValueError("Unsupported AAOCA review scope; expected exception_patients_only")

    source_hashes = {
        "source_run_metadata_sha256": sha256_file(run_metadata_path),
        "source_patient_manifest_sha256": sha256_file(manifest_path),
        "source_section_index_sha256": sha256_file(section_index_path),
    }
    for key, actual in source_hashes.items():
        expected = review_metadata.get(key)
        if expected and expected != actual:
            raise ValueError(f"AAOCA review source hash mismatch: {key}")

    manifest = _read_csv(manifest_path)
    cases = _read_csv(cases_path)
    manifest_ids = [row.get("patient_id", "") for row in manifest]
    if not manifest_ids or len(set(manifest_ids)) != len(manifest_ids) or "" in manifest_ids:
        raise ValueError("patient_manifest.csv must contain unique nonempty patient_id values")
    case_by_patient: dict[str, dict] = {}
    for row in cases:
        patient_id = row.get("patient_id", "")
        if not patient_id or patient_id in case_by_patient or patient_id not in set(manifest_ids):
            raise ValueError("exception_cases.csv has an invalid or duplicate patient_id")
        automatic = row.get("automatic_aaoca_judgment", "")
        if automatic not in {"yes", "no", "uncertain"}:
            raise ValueError(f"Invalid automatic AAOCA judgment for {patient_id}")
        review_status = row.get("review_status", "not_reviewed")
        final = row.get("final_aaoca_judgment", "")
        if review_status == "reviewed" and final not in {"yes", "no", "uncertain"}:
            raise ValueError(f"Reviewed AAOCA exception lacks a final label: {patient_id}")
        if review_status != "reviewed" and final:
            raise ValueError(f"Incomplete AAOCA review has a final label: {patient_id}")
        case_by_patient[patient_id] = row

    expected_exceptions = int(review_metadata.get("exception_patients", -1))
    expected_nonexceptions = int(review_metadata.get("nonexception_patients", -1))
    if expected_exceptions != len(cases) or expected_nonexceptions != len(manifest) - len(cases):
        raise ValueError("AAOCA review exception/nonexception counts do not match the source cohort")

    selection = []
    for patient_id in manifest_ids:
        case = case_by_patient.get(patient_id)
        if case:
            reviewed = case.get("review_status") == "reviewed"
            judgment = case.get("final_aaoca_judgment") if reviewed else case.get("automatic_aaoca_judgment")
            source = "human_final_exception" if reviewed else "automatic_exception"
            review_status = case.get("review_status", "not_reviewed")
        else:
            judgment = "yes"
            source = "automatic_nonexception"
            review_status = "not_applicable"
        selection.append(
            {
                "patient_id": patient_id,
                "aaoca_judgment": judgment,
                "judgment_source": source,
                "review_status": review_status,
                "included_for_management": judgment == "yes",
                "exclusion_reason": "" if judgment == "yes" else f"aaoca_{judgment}",
            }
        )

    receipt = {
        "patients_total": len(selection),
        "included_patients": sum(row["included_for_management"] for row in selection),
        "aaoca_judgments": dict(Counter(row["aaoca_judgment"] for row in selection)),
        "judgment_sources": dict(Counter(row["judgment_source"] for row in selection)),
        "source_hashes": source_hashes,
    }
    return selection, receipt


def load_sections(run_root: Path, patient_ids: set[str]) -> list[dict]:
    """Load full section text for selected patients and reject duplicate IDs."""

    sections_dir = run_root / "sections"
    if not sections_dir.is_dir():
        raise ValueError("Completed pipeline snapshot is missing sections/")
    result: list[dict] = []
    seen: set[str] = set()
    for path in sorted(sections_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for section in payload.get("sections", []):
            if section.get("patient_id") not in patient_ids:
                continue
            section_id = section.get("section_id", "")
            if not section_id or section_id in seen:
                raise ValueError(f"Missing or duplicate section_id: {section_id}")
            seen.add(section_id)
            result.append(section)
    return result


AAOCA_ANCHOR_RE = re.compile(
    r"AAOCA|冠(?:状动)?脉.{0,35}(?:异常起源|起源异常|异位起源|开口异常|壁内走行)|"
    r"(?:左|右)冠(?:状动脉)?.{0,25}(?:起自|起源于|发自).{0,25}(?:冠窦|主动脉|肺动脉)",
    re.IGNORECASE | re.DOTALL,
)

SPECIFIC_AAOCA_DIAG_RE = re.compile(
    r"AAOCA|AORCA|ALCA(?:PA)?|冠状动脉起源异常|冠脉起源异常|冠状动脉异常起源|冠脉异常起源|"
    r"(?:左|右)冠(?:状动脉)?.{0,18}(?:起自|起源于|发自).{0,18}(?:冠窦|主动脉)",
    re.I | re.DOTALL,
)

OTHER_SURGICAL_LESION_RE = re.compile(
    r"房间隔缺损|室间隔缺损|房室间隔缺损|动脉导管未闭|肺静脉异位引流|主动脉缩窄|"
    r"右室流出道狭窄|法洛四联症|肺动脉瓣狭窄|二尖瓣.{0,5}(?:关闭不全|反流|狭窄)|"
    r"三尖瓣.{0,5}(?:关闭不全|反流|狭窄)",
    re.I | re.DOTALL,
)

OPERATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("coronary_unroofing", re.compile(r"(?:冠状动脉|冠脉|左冠|右冠|RCA|LCA).{0,20}(?:去顶|unroof)", re.I)),
    ("coronary_ostial_reconstruction", re.compile(r"(?:冠状动脉|冠脉|左冠|右冠).{0,14}(?:开口|开又).{0,3}(?:成形|扩大|修补)", re.I)),
    ("coronary_reimplantation", re.compile(r"(?:冠状动脉|冠脉|左冠|右冠).{0,6}(?:再植|移植|转位)", re.I)),
    ("coronary_origin_correction", re.compile(r"(?:冠状动脉|冠脉).{0,12}(?:异常起源|起源异常).{0,8}(?:纠治|矫治|修复)", re.I)),
    ("coronary_origin_correction", re.compile(r"(?:冠状动脉|冠脉).{0,8}畸形.{0,5}(?:纠治|矫正|矫治|修复)", re.I)),
    (
        "coronary_anomaly_repair_unspecified",
        re.compile(r"(?:左|右)冠(?:状动脉)?开口高位手术", re.I),
    ),
    ("coronary_bypass", re.compile(r"(?:冠状动脉|冠脉).{0,10}(?:搭桥|旁路)", re.I)),
    ("coronary_reconstruction", re.compile(r"(?:冠状动脉|冠脉|左冠|右冠).{0,10}(?:重建|松解)", re.I)),
    ("coronary_repair", re.compile(r"(?:冠状动脉|冠脉).{0,6}修补术", re.I)),
]

DIAGNOSTIC_PROCEDURE_RE = re.compile(
    r"冠(?:状动)?脉造影|升主动脉造影|左右心联合造影|心导管检查|右心导管|左心导管|血管造影",
    re.I,
)

THERAPEUTIC_OPERATION_RE = re.compile(
    r"(?:手术|修补|成形|置换|切除|结扎|矫治|纠治|缝合|探查|开胸|搭桥|旁路|移植|再植|转位|封堵)",
    re.I,
)

ADJUNCT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("adjunct_pulmonary_artery_plasty", re.compile(r"肺动脉.{0,10}(?:补片|扩大|成形|移位|转位)", re.I)),
]

FIELD_RE = re.compile(
    r"(?P<label>拟施手术名称和方式|拟行手术名称和方式|拟定手术方式|手术方案|手术名称|手术方式|操作名称)\s*[:：]?\s*"
    r"(?P<value>.{1,260}?)(?=拟施麻醉|手术医生|手术医师|操作目的|家属是否|麻醉方式|"
    r"手术简要经过|手术经过|巡回护士|洗手护士|病理检查|术中出血|记录医师|"
    r"可能出现的意外|是否需要分次|具体讨论意见|主持人小结|$)",
    re.I | re.DOTALL,
)

SPECIFIC_OPERATION_RE = re.compile(
    "|".join(f"(?:{pattern.pattern})" for _, pattern in OPERATION_PATTERNS),
    re.I | re.DOTALL,
)

PLAN_CUE_RE = re.compile(r"拟(?:行|施|于)?|计划|建议|考虑|准备|待行|欲行|手术方案|手术指征|具备手术指征", re.I)
COMPLETION_CUE_RE = re.compile(
    r"手术记录|手术时间|手术经过|术后(?:第?\s*\d+|恢复|状态|诊断)|"
    r"(?:已|曾|既往|于.{0,30})行|完成.{0,20}(?:手术|治疗)|接受.{0,20}手术|术顺",
    re.I | re.DOTALL,
)
CANCEL_CUE_RE = re.compile(r"取消|暂缓|拒绝|放弃|未行|未能行|终止", re.I)


def _procedure_types(value: str) -> list[str]:
    compact = _compact(value)
    types = [name for name, pattern in OPERATION_PATTERNS if pattern.search(compact)]
    if re.search(r"冠状动脉瘤|冠脉瘤", compact, re.I):
        # Repair of a coronary aneurysm is a different indication; the word
        # sequence must not be mistaken for generic coronary repair in AAOCA.
        types = [name for name in types if name != "coronary_repair"]
    if types:
        types.extend(name for name, pattern in ADJUNCT_PATTERNS if pattern.search(compact))
    return list(dict.fromkeys(types))


def _date_evidence(
    section: dict, start: int, end: int, completed: bool
) -> tuple[str, str, str, str, list[str], list[str]]:
    """Return date, precision, role, status, candidates and conflict flags."""

    text = section.get("text", "")
    explicit: list[str] = []
    if completed:
        for match in re.finditer(r"手术时间\s*[:：]?\s*(.{0,45})", text, re.I | re.DOTALL):
            explicit.extend(_dates_in(match.group(1)))
    window = text[max(0, start - 100): min(len(text), end + 70)]
    local = _dates_in(window)
    local_months = _months_in(window)
    section_date = section.get("section_date", "")
    candidates = list(dict.fromkeys(explicit + local + local_months + ([section_date] if section_date else [])))
    flags: list[str] = []
    if completed and explicit:
        selected = explicit[0]
        role = "performed"
        if len(set(explicit)) > 1:
            flags.append("multiple_surgery_time_dates")
    elif completed:
        # A date is a performed date only when it is syntactically tied to a
        # completed operation.  Ordinary daily-note dates must not create a new
        # surgery event for every postoperative day.
        tied_dates: list[str] = []
        for match in DATE_RE.finditer(window):
            day = _iso_date(match)
            after = window[match.end(): min(len(window), match.end() + 100)]
            if day and re.match(
                r"\s*(?:(?:于|在)\s*(?:我院|本院|外院)?.{0,20})?(?:(?:已|曾|予)\s*)?(?:行|接受|完成)",
                after,
                re.I | re.DOTALL,
            ):
                tied_dates.append(day)
        tied_dates = list(dict.fromkeys(tied_dates))
        if tied_dates:
            selected = tied_dates[-1]
            role = "historical_performed"
        else:
            tied_months: list[str] = []
            for match in MONTH_RE.finditer(window):
                month = f"{int(match.group('year')):04d}-{int(match.group('month')):02d}"
                after = window[match.end(): min(len(window), match.end() + 110)]
                if re.match(
                    r"\s*(?:(?:于|在)\s*(?:我院|本院|外院)?.{0,35})?(?:(?:已|曾|予)\s*)?(?:行|接受|完成)",
                    after,
                    re.I | re.DOTALL,
                ):
                    tied_months.append(month)
            tied_months = list(dict.fromkeys(tied_months))
            if tied_months:
                selected = tied_months[-1]
                role = "historical_performed_month"
            else:
                postoperative_day = re.search(r"术后第?\s*(\d{1,3})\s*天", window)
                if postoperative_day and section_date:
                    try:
                        selected = (date.fromisoformat(section_date) - timedelta(days=int(postoperative_day.group(1)))).isoformat()
                        role = "inferred_from_postoperative_day"
                        candidates.insert(0, selected)
                    except ValueError:
                        selected, role = "", "unknown"
                elif section.get("section_subtype") == "postop_progress" and re.search(r"术后首次", window) and section_date:
                    selected, role = section_date, "inferred_same_day_postoperative_note"
                elif section.get("section_subtype") == "surgery_record" and section_date:
                    selected, role = section_date, "surgery_record_section_date"
                else:
                    selected, role = "", "unknown"
    elif local:
        selected = local[0]
        role = "planned_or_section"
    elif local_months:
        selected = local_months[0]
        role = "planned_or_section_month"
    elif section_date:
        selected = section_date
        role = "section_date"
    else:
        return "", "unknown", "unknown", "unknown", [], flags
    if completed and explicit and section_date and selected != section_date:
        flags.append("section_and_surgery_date_conflict")
    precision = "day" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected) else "month" if selected else "unknown"
    status = "unknown" if not selected else "conflict" if flags else "partial" if precision == "month" else "known"
    return selected, precision, role, status, candidates, flags


def _evidence_row(
    section: dict,
    *,
    rule_id: str,
    assertion: str,
    event_kind: str,
    strength: str,
    relation: str,
    counts_as_surgery: bool,
    procedure_name: str,
    procedure_types: list[str],
    start: int,
    end: int,
    extra_flags: Iterable[str] = (),
) -> dict:
    text = section.get("text", "")
    clip_start = max(0, start - 180)
    clip_end = min(len(text), end + 220)
    completed = assertion in {"completed", "diagnostic_completed", "unrelated_completed"}
    evidence_date, date_precision, date_role, date_status, date_candidates, date_flags = _date_evidence(
        section, clip_start, clip_end, completed
    )
    flags = list(dict.fromkeys([*extra_flags, *date_flags]))
    evidence_id = _stable_id(
        "mge",
        section.get("patient_id", ""),
        section.get("section_id", ""),
        rule_id,
        assertion,
        start,
        end,
        procedure_name,
    )
    return {
        "patient_id": section.get("patient_id", ""),
        "evidence_id": evidence_id,
        "rule_id": rule_id,
        "assertion": assertion,
        "event_kind": event_kind,
        "strength": strength,
        "aaoca_relation": relation,
        "counts_as_aaoca_surgery": counts_as_surgery,
        "procedure_name_raw": procedure_name,
        "procedure_types": procedure_types,
        "evidence_date": evidence_date,
        "date_precision": date_precision,
        "date_role": date_role,
        "date_status": date_status,
        "date_candidates": date_candidates,
        "document_id": section.get("document_id", ""),
        "section_id": section.get("section_id", ""),
        "section_type": section.get("section_type", ""),
        "section_subtype": section.get("section_subtype", ""),
        "section_date": section.get("section_date", ""),
        "page_start": section.get("page_start", ""),
        "page_end": section.get("page_end", ""),
        "text_source": section.get("text_source", ""),
        "date_requires_review": section.get("date_requires_review", False),
        "parse_status": section.get("parse_status", ""),
        "source_pdf": section.get("source_pdf", ""),
        "text_path": section.get("text_path", ""),
        "text_reference": section.get("text_reference", ""),
        "char_start": clip_start,
        "char_end": clip_end,
        "evidence_text": text[clip_start:clip_end],
        "flags": flags,
    }


class ManagementEvidenceExtractor(Protocol):
    def extract(self, section: dict) -> list[dict]:
        """Return provenance-bearing management assertions for one section."""
        ...


@dataclass(frozen=True)
class DeterministicManagementEvidenceExtractor:
    ruleset_version: str = RULESET_VERSION

    def extract(self, section: dict) -> list[dict]:
        text = section.get("text", "")
        if not text or section.get("section_type") in {"laboratory", "nonclinical"}:
            return []
        rows: list[dict] = []
        field_matches = list(FIELD_RE.finditer(text))

        for match in field_matches:
            label = match.group("label")
            value = match.group("value").strip()
            types = _procedure_types(value)
            is_planned_field = label.startswith("拟")
            subtype = section.get("section_subtype", "")
            planning_context = subtype in {
                "preoperative_discussion",
                "treatment_procedure_consent",
                "condition_communication",
            } or (section.get("section_type") == "administrative" and "知情同意" in text[:240])
            if types:
                if is_planned_field or planning_context:
                    assertion, rule_id, strength = "intended", "specific_aaoca_operation_planned", "high"
                elif subtype in {"surgery_record", "postop_progress"} or COMPLETION_CUE_RE.search(text):
                    assertion, rule_id, strength = "completed", "specific_aaoca_operation_completed", "high"
                else:
                    window = text[max(0, match.start() - 100): min(len(text), match.end() + 100)]
                    if PLAN_CUE_RE.search(window) and not COMPLETION_CUE_RE.search(window):
                        assertion, rule_id, strength = "intended", "specific_aaoca_operation_planned", "high"
                    elif COMPLETION_CUE_RE.search(window):
                        assertion, rule_id, strength = "completed", "specific_aaoca_operation_completed", "medium"
                    else:
                        continue
                rows.append(
                    _evidence_row(
                        section,
                        rule_id=rule_id,
                        assertion=assertion,
                        event_kind="aaoca_surgery",
                        strength=strength,
                        relation="definite",
                        counts_as_surgery=assertion == "completed",
                        procedure_name=value,
                        procedure_types=types,
                        start=match.start(),
                        end=match.end(),
                    )
                )
            elif DIAGNOSTIC_PROCEDURE_RE.search(_compact(value)):
                assertion = "intended" if is_planned_field or planning_context else "diagnostic_completed"
                rows.append(
                    _evidence_row(
                        section,
                        rule_id="coronary_diagnostic_procedure_not_surgery",
                        assertion=assertion,
                        event_kind="diagnostic_procedure",
                        strength="high",
                        relation="related_nontherapeutic",
                        counts_as_surgery=False,
                        procedure_name=value,
                        procedure_types=["coronary_diagnostic_procedure"],
                        start=match.start(),
                        end=match.end(),
                        extra_flags=["does_not_count_as_aaoca_surgery"],
                    )
                )
            elif (
                subtype == "surgery_record"
                and not is_planned_field
                and THERAPEUTIC_OPERATION_RE.search(_compact(value))
            ):
                # Preserve an auditable negative decision boundary.  A real
                # operation in an AAOCA patient's chart is not necessarily an
                # AAOCA operation (ASD/VSD repair is a common example).  These
                # rows never affect the surgery event builder, but make the
                # exclusion inspectable and give later review/LLM stages the
                # exact source span instead of silently discarding it.
                flags = ["does_not_count_as_aaoca_surgery"]
                if AAOCA_ANCHOR_RE.search(text):
                    flags.append("aaoca_relation_not_established_by_rule")
                rows.append(
                    _evidence_row(
                        section,
                        rule_id="completed_operation_not_aaoca_matched",
                        assertion="unrelated_completed",
                        event_kind="other_surgery",
                        strength="high",
                        relation="unrelated_or_unresolved",
                        counts_as_surgery=False,
                        procedure_name=value,
                        procedure_types=[],
                        start=match.start(),
                        end=match.end(),
                        extra_flags=flags,
                    )
                )

        # A named operation outside a well-formed field is still useful when
        # completion or planning is explicit.  This recovers historical and
        # discharge-summary evidence without treating a bare diagnosis as an
        # operation.
        for match in SPECIFIC_OPERATION_RE.finditer(text):
            window_start = max(0, match.start() - 100)
            window_end = min(len(text), match.end() + 110)
            window = text[window_start:window_end]
            types = _procedure_types(match.group(0))
            if not types:
                continue
            relation_window = text[max(0, match.start() - 260): min(len(text), match.end() + 260)]
            if not AAOCA_ANCHOR_RE.search(relation_window):
                # Coronary bypass/reconstruction language also occurs in
                # electrophysiology risk plans and other non-AAOCA contexts.
                # A free-text operation mention therefore needs a local AAOCA
                # anchor.  Structured operation fields are assessed above.
                continue
            cancelled = CANCEL_CUE_RE.search(window) and PLAN_CUE_RE.search(window)
            planned = PLAN_CUE_RE.search(window)
            completed = COMPLETION_CUE_RE.search(window)
            subtype = section.get("section_subtype", "")
            planning_context = subtype in {
                "preoperative_discussion",
                "treatment_procedure_consent",
                "condition_communication",
            } or (section.get("section_type") == "administrative" and "知情同意" in text[:240])
            explicitly_not_performed = re.search(
                r"(?:未行|无法行|未予|不予|无需|无须|暂不).{0,16}(?:去顶|修补|纠治|矫治|成形|扩大|移植|再植|转位|处理)",
                window,
                re.I | re.DOTALL,
            )
            if explicitly_not_performed:
                assertion, rule_id, strength = "conservative", "specific_aaoca_operation_explicitly_not_performed", "high"
            elif cancelled and not re.search(r"术后|已行|手术记录", window):
                assertion, rule_id, strength = "cancelled_or_declined", "aaoca_operation_cancelled_or_declined", "high"
            elif planning_context or (planned and not completed):
                assertion, rule_id, strength = "intended", "specific_aaoca_operation_planned", "high"
            elif subtype in {"surgery_record", "postop_progress"} or completed:
                assertion = "completed"
                rule_id = "specific_aaoca_operation_completed"
                strength = "high" if subtype in {"surgery_record", "postop_progress"} else "medium"
            else:
                continue
            rows.append(
                _evidence_row(
                    section,
                    rule_id=rule_id,
                    assertion=assertion,
                    event_kind="aaoca_surgery",
                    strength=strength,
                    relation="definite",
                    counts_as_surgery=assertion == "completed",
                    procedure_name=match.group(0),
                    procedure_types=types,
                    start=window_start,
                    end=window_end,
                )
            )

        rows.extend(self._extract_nonoperative_decisions(section, bool(field_matches)))
        return self._deduplicate(rows)

    def _extract_nonoperative_decisions(self, section: dict, has_operation_field: bool) -> list[dict]:
        text = section.get("text", "")
        rows: list[dict] = []
        patterns = [
            (
                "aaoca_explicit_nonoperative_plan",
                re.compile(
                    r"(?:冠状动脉|冠脉|左冠|右冠|AAOCA)[^。；;\n]{0,80}"
                    r"(?:未予处理|未处理|不予处理|无需(?:特殊)?处理|无须(?:特殊)?处理|暂无需(?:特殊)?处理|"
                    r"(?:手术)?暂不处理|不予(?:手术|干预|治疗)|无需(?:手术|干预)|暂不(?:手术)?干预)|"
                    r"(?:未予处理|未处理|不予处理|无需(?:特殊)?处理|无须(?:特殊)?处理|暂无需(?:特殊)?处理|"
                    r"(?:手术)?暂不处理|不予(?:手术|干预|治疗)|无需(?:手术|干预)|暂不(?:手术)?干预)"
                    r"[^。；;\n]{0,80}(?:冠状动脉|冠脉|左冠|右冠|AAOCA)",
                    re.I | re.DOTALL,
                ),
                "high",
            ),
            (
                "aaoca_historical_observation",
                re.compile(
                    r"(?:冠状动脉|冠脉|左冠|右冠|AAOCA)[^。；;\n]{0,70}"
                    r"(?:未予特殊(?:处理|治疗)|未进一步治疗|定期随访观察)|"
                    r"(?:未予特殊(?:处理|治疗)|未进一步治疗|定期随访观察)"
                    r"[^。；;\n]{0,70}(?:冠状动脉|冠脉|左冠|右冠|AAOCA)",
                    re.I | re.DOTALL,
                ),
                "medium",
            ),
            (
                "aaoca_no_surgical_indication",
                re.compile(
                    r"(?:冠状动脉|冠脉|AAOCA)[^。；;\n]{0,120}(?:无|暂无|不具备)\s*手术指征|"
                    r"(?:无|暂无|不具备)\s*手术指征[^。；;\n]{0,120}(?:冠状动脉|冠脉|AAOCA)",
                    re.I | re.DOTALL,
                ),
                "high",
            ),
            (
                "aaoca_followup_observation",
                re.compile(
                    r"(?:冠状动脉|冠脉|右冠|左冠|AAOCA)[^。；;\n]{0,140}(?:心内科)?(?:门诊|定期)?随访|"
                    r"会诊意见[^。；;\n]{0,120}(?:心内科)?门诊随访",
                    re.I | re.DOTALL,
                ),
                "medium",
            ),
        ]
        for rule_id, pattern, strength in patterns:
            for match in pattern.finditer(text):
                window = text[max(0, match.start() - 140): min(len(text), match.end() + 140)]
                if not AAOCA_ANCHOR_RE.search(window) and rule_id != "aaoca_followup_observation":
                    continue
                if rule_id == "aaoca_followup_observation" and not AAOCA_ANCHOR_RE.search(text[max(0, match.start() - 420):match.end()]):
                    continue
                if rule_id == "aaoca_followup_observation" and re.search(r"(?:会诊|胸外科)[^。；;\n]{0,30}或[^。；;\n]{0,30}随访", window):
                    continue
                if re.search(r"家属[^。；;\n]{0,30}(?:认为|自行)", window):
                    continue
                rows.append(
                    _evidence_row(
                        section,
                        rule_id=rule_id,
                        assertion="conservative",
                        event_kind="management_decision",
                        strength=strength,
                        relation="definite" if strength == "high" else "probable",
                        counts_as_surgery=False,
                        procedure_name="",
                        procedure_types=[],
                        start=match.start(),
                        end=match.end(),
                    )
                )

        cancel_pattern = re.compile(
            r"(?:AAOCA|AORCA|冠状动脉起源异常|冠脉起源异常|冠状动脉异常起源|冠脉异常起源)"
            r"[^。；;\n]{0,90}(?:(?:取消|暂缓|拒绝|放弃|未行|未能行)[^。；;\n]{0,20}手术|暂不手术)|"
            r"(?:(?:取消|暂缓|拒绝|放弃|未行|未能行)[^。；;\n]{0,20}手术|暂不手术)"
            r"[^。；;\n]{0,90}(?:AAOCA|AORCA|冠状动脉起源异常|冠脉起源异常|冠状动脉异常起源|冠脉异常起源)",
            re.I | re.DOTALL,
        )
        for match in cancel_pattern.finditer(text):
            window = text[max(0, match.start() - 100): min(len(text), match.end() + 100)]
            if OTHER_SURGICAL_LESION_RE.search(window):
                continue
            rows.append(
                _evidence_row(
                    section,
                    rule_id="aaoca_surgery_cancelled_or_declined",
                    assertion="cancelled_or_declined",
                    event_kind="surgical_intent",
                    strength="high",
                    relation="definite",
                    counts_as_surgery=False,
                    procedure_name="",
                    procedure_types=[],
                    start=match.start(),
                    end=match.end(),
                )
            )

        # A close grammatical link between the anomalous coronary and surgery
        # is enough to establish intent even when another lesion is present.
        # It still cannot establish that surgery happened.  This covers
        # phrases such as "右冠异常后续可能需外科手术纠治" while avoiding
        # a bare "进一步处理" that may only mean more diagnostic work-up.
        specific_intent_pattern = re.compile(
            r"(?:AAOCA|AORCA|冠状动脉起源异常|冠脉起源异常|冠状动脉异常起源|冠脉异常起源|"
            r"(?:左|右)冠(?:状动脉)?(?:起源)?异常|(?:左|右)冠(?:状动脉)?.{0,18}(?:起自|起源于|发自).{0,18}(?:冠窦|主动脉))"
            r"[^。；;\n]{0,60}(?:(?:后续|择期|必要时|评估后|检查后)?(?:仍|可能)?(?:拟|计划|建议|考虑|需|需要)"
            r"[^。；;\n]{0,20}(?:手术治疗|外科手术|外科治疗|手术干预|外科[^。；;\n]{0,10}纠治|手术[^。；;\n]{0,10}纠治)|"
            r"(?:评估|检查|讨论)[^。；;\n]{0,24}是否(?:需要)?[^。；;\n]{0,10}(?:手术|外科治疗))",
            re.I | re.DOTALL,
        )
        for match in specific_intent_pattern.finditer(text):
            rows.append(
                _evidence_row(
                    section,
                    rule_id="specific_aaoca_surgical_intent",
                    assertion="intended",
                    event_kind="surgical_intent",
                    strength="medium",
                    relation="definite",
                    counts_as_surgery=False,
                    procedure_name="",
                    procedure_types=[],
                    start=match.start(),
                    end=match.end(),
                )
            )

        # Generic intent is deliberately narrow.  A nearby mention of a
        # coronary finding does not make an ASD/VSD operation an AAOCA plan.
        # Named AAOCA procedures are handled above; this fallback requires an
        # explicit AAOCA diagnosis as the local grammatical subject and no
        # competing structural lesion in the same clause.
        if not has_operation_field:
            intent_pattern = re.compile(
                r"(?:AAOCA|AORCA|冠状动脉起源异常|冠脉起源异常|冠状动脉异常起源|冠脉异常起源)"
                r"[^。；;\n]{0,55}(?:拟|计划|建议|考虑|准备|需|具备)[^。；;\n]{0,16}"
                r"(?:手术治疗|外科手术|外科治疗|手术干预|手术指征)|"
                r"(?:拟|计划|建议|考虑|准备|需|具备)[^。；;\n]{0,16}"
                r"(?:手术治疗|外科手术|外科治疗|手术干预|手术指征)[^。；;\n]{0,55}"
                r"(?:AAOCA|AORCA|冠状动脉起源异常|冠脉起源异常|冠状动脉异常起源|冠脉异常起源)",
                re.I | re.DOTALL,
            )
            for match in intent_pattern.finditer(text):
                window = text[max(0, match.start() - 80): min(len(text), match.end() + 80)]
                if OTHER_SURGICAL_LESION_RE.search(window):
                    continue
                rows.append(
                    _evidence_row(
                        section,
                        rule_id="generic_aaoca_surgical_intent",
                        assertion="intended",
                        event_kind="surgical_intent",
                        strength="medium",
                        relation="probable",
                        counts_as_surgery=False,
                        procedure_name="",
                        procedure_types=[],
                        start=match.start(),
                        end=match.end(),
                    )
                )
        return rows

    @staticmethod
    def _deduplicate(rows: list[dict]) -> list[dict]:
        priority = {"high": 2, "medium": 1, "low": 0}
        best: dict[tuple, dict] = {}
        for row in rows:
            key = (
                row["section_id"],
                row["assertion"],
                tuple(row["procedure_types"]),
                row["evidence_date"],
                row["rule_id"],
            )
            current = best.get(key)
            if current is None or priority[row["strength"]] > priority[current["strength"]]:
                best[key] = row
        return sorted(best.values(), key=lambda row: (row["char_start"], row["rule_id"], row["evidence_id"]))


def extract_management_evidence(
    sections: Iterable[dict], extractor: ManagementEvidenceExtractor | None = None
) -> list[dict]:
    extractor = extractor or DeterministicManagementEvidenceExtractor()
    rows: list[dict] = []
    for section in sections:
        rows.extend(extractor.extract(section))
    unique = {row["evidence_id"]: row for row in rows}
    return sorted(
        unique.values(),
        key=lambda row: (
            row["patient_id"],
            row["evidence_date"] or "9999-99-99",
            row["document_id"],
            row["section_id"],
            row["char_start"],
            row["evidence_id"],
        ),
    )


def _evidence_priority(row: dict) -> tuple:
    subtype_priority = {
        "surgery_record": 5,
        "postop_progress": 4,
        "transfer": 3,
        "": 2,
    }
    strength_priority = {"high": 3, "medium": 2, "low": 1}
    source_priority = 0 if row.get("text_source") == "local_ocr" else 1
    return (
        subtype_priority.get(row.get("section_subtype", ""), 1),
        strength_priority.get(row.get("strength", ""), 0),
        source_priority,
        bool(row.get("evidence_date")),
        -int(row.get("char_start") or 0),
    )


def _event_from_evidence(patient_id: str, surgery_date: str, rows: list[dict], unknown_key: str = "") -> dict:
    rows = sorted(rows, key=_evidence_priority, reverse=True)
    primary = rows[0]
    procedure_types = list(
        dict.fromkeys(item for row in rows for item in _json_list(row.get("procedure_types")))
    )
    procedure_names = list(
        dict.fromkeys(row.get("procedure_name_raw", "").strip() for row in rows if row.get("procedure_name_raw", "").strip())
    )
    evidence_ids = list(dict.fromkeys(row["evidence_id"] for row in rows))
    formal = any(row.get("section_subtype") == "surgery_record" for row in rows)
    postop = any(row.get("section_subtype") == "postop_progress" or "术后" in row.get("evidence_text", "") for row in rows)
    conflict_flags = list(
        dict.fromkeys(flag for row in rows for flag in _json_list(row.get("flags")))
    )
    if not surgery_date:
        conflict_flags.append("surgery_date_unknown")
    date_precision = (
        "day" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", surgery_date) else "month" if surgery_date else "unknown"
    )
    date_conflict = any(
        flag in {"section_and_surgery_date_conflict", "multiple_surgery_time_dates"}
        or "date_conflict" in flag
        for flag in conflict_flags
    )
    date_status = (
        "unknown" if not surgery_date else "conflict" if date_conflict else "partial" if date_precision == "month" else "known"
    )
    historical_only = not formal and not postop
    confidence = "high" if formal and surgery_date and date_status == "known" else "medium"
    event_id = _stable_id(
        "surg",
        patient_id,
        surgery_date or f"unknown:{unknown_key}",
        "|".join(sorted(procedure_types)),
    )
    return {
        "patient_id": patient_id,
        "surgery_event_id": event_id,
        "surgery_date": surgery_date,
        "surgery_date_precision": date_precision,
        "date_status": date_status,
        "procedure_types": procedure_types,
        "procedure_names": procedure_names,
        "n_supporting_evidence": len(evidence_ids),
        "primary_evidence_id": primary["evidence_id"],
        "supporting_evidence_ids": evidence_ids,
        "formal_surgery_record_present": formal,
        "postoperative_evidence_present": postop,
        "historical_only": historical_only,
        "relation_confidence": confidence,
        "source_document_ids": list(dict.fromkeys(row["document_id"] for row in rows)),
        "source_section_ids": list(dict.fromkeys(row["section_id"] for row in rows)),
        "primary_document_id": primary["document_id"],
        "primary_section_id": primary["section_id"],
        "primary_page_start": primary["page_start"],
        "primary_page_end": primary["page_end"],
        "primary_text_path": primary["text_path"],
        "primary_text_reference": primary["text_reference"],
        "conflict_flags": list(dict.fromkeys(conflict_flags)),
    }


def build_surgery_events(evidence: Iterable[dict]) -> list[dict]:
    """Deduplicate repeated descriptions while preserving separate dates."""

    by_patient: dict[str, list[dict]] = defaultdict(list)
    for row in evidence:
        if row.get("assertion") == "completed" and _bool(row.get("counts_as_aaoca_surgery")):
            by_patient[row["patient_id"]].append(row)

    events: list[dict] = []
    for patient_id, rows in sorted(by_patient.items()):
        formal_rows = [row for row in rows if row.get("section_subtype") == "surgery_record"]
        if formal_rows:
            # Formal operation records define the event anchors.  Postoperative
            # notes commonly repeat the operation on every day of recovery;
            # their section date is not a new surgery date.  A clearly dated
            # historical operation far from every formal anchor is retained as
            # a separate event.
            formal_groups: dict[str, list[dict]] = defaultdict(list)
            for row in formal_rows:
                key = row.get("evidence_date") or f"document:{row['document_id']}"
                formal_groups[key].append(row)
            historical_groups: dict[str, list[dict]] = defaultdict(list)
            for row in [candidate for candidate in rows if candidate not in formal_rows]:
                row_day = row.get("evidence_date", "")
                formal_days = [key for key in formal_groups if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key)]
                distant_historical = False
                if row.get("date_role") == "historical_performed" and row_day and formal_days:
                    row_date = date.fromisoformat(row_day)
                    distant_historical = all(
                        abs((row_date - date.fromisoformat(day)).days) > 90 for day in formal_days
                    )
                if distant_historical:
                    historical_groups[row_day].append(row)
                    continue
                if len(formal_groups) == 1:
                    next(iter(formal_groups.values())).append(row)
                    continue
                row_types = set(_json_list(row.get("procedure_types")))
                compatible = [
                    key
                    for key, candidates in formal_groups.items()
                    if row_types & {item for candidate in candidates for item in _json_list(candidate.get("procedure_types"))}
                ]
                if row_day and row_day in formal_groups:
                    formal_groups[row_day].append(row)
                elif row_day and compatible:
                    dated_compatible = [key for key in compatible if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key)]
                    if dated_compatible:
                        nearest = min(
                            dated_compatible,
                            key=lambda day: abs((date.fromisoformat(row_day) - date.fromisoformat(day)).days),
                        )
                        formal_groups[nearest].append(row)
                elif len(compatible) == 1:
                    formal_groups[compatible[0]].append(row)
                # Ambiguous copied history remains in management_evidence.csv
                # but cannot manufacture another event without a distinct date.
            for key, candidates in sorted(formal_groups.items()):
                day = key if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key) else ""
                events.append(_event_from_evidence(patient_id, day, candidates, key))
            for day, candidates in sorted(historical_groups.items()):
                events.append(_event_from_evidence(patient_id, day, candidates, f"historical:{day}"))
            continue

        dated: dict[str, list[dict]] = defaultdict(list)
        undated: list[dict] = []
        for row in rows:
            if row.get("evidence_date"):
                dated[row["evidence_date"]].append(row)
            else:
                undated.append(row)

        # Attach an undated repeated mention to a single compatible dated
        # operation.  If several dated operations are compatible, retaining an
        # explicit unknown cluster is safer than guessing which event it means.
        remaining: list[dict] = []
        for row in undated:
            row_types = set(_json_list(row.get("procedure_types")))
            compatible = [
                day
                for day, candidates in dated.items()
                if row_types & {item for candidate in candidates for item in _json_list(candidate.get("procedure_types"))}
            ]
            if len(compatible) == 1:
                dated[compatible[0]].append(row)
            else:
                remaining.append(row)

        for day, candidates in sorted(dated.items()):
            events.append(_event_from_evidence(patient_id, day, candidates))

        # Unknown-date mentions with the same procedure family are one minimum
        # event, not one event per copied discharge/history paragraph.
        unknown_groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
        for row in remaining:
            key = tuple(sorted(_json_list(row.get("procedure_types")))) or ("unspecified_aaoca_surgery",)
            unknown_groups[key].append(row)
        for key, candidates in sorted(unknown_groups.items()):
            events.append(_event_from_evidence(patient_id, "", candidates, "|".join(key)))

    return sorted(events, key=lambda row: (row["patient_id"], row["surgery_date"] or "9999-99-99", row["surgery_event_id"]))


def _latest_date(rows: Iterable[dict]) -> str:
    return max((row.get("evidence_date", "") for row in rows if row.get("evidence_date")), default="")


def _patient_summary(
    patient_id: str,
    judgment_source: str,
    evidence: list[dict],
    events: list[dict],
) -> tuple[dict, list[dict]]:
    completed = [row for row in evidence if row["assertion"] == "completed" and _bool(row["counts_as_aaoca_surgery"])]
    intended = [row for row in evidence if row["assertion"] == "intended" and row["event_kind"] != "diagnostic_procedure"]
    cancelled = [row for row in evidence if row["assertion"] == "cancelled_or_declined"]
    conservative = [row for row in evidence if row["assertion"] == "conservative"]
    diagnostics = [row for row in evidence if row["assertion"] == "diagnostic_completed"]
    unrelated = [row for row in evidence if row["assertion"] == "unrelated_completed"]
    qc: list[dict] = []
    review_reasons: list[str] = []

    if events:
        management = "surgery"
        surgery_status = "yes"
        rule = "completed_aaoca_surgery_evidence"
        primary_event = max(events, key=lambda row: (row["relation_confidence"] == "high", bool(row["surgery_date"]), row["surgery_date"]))
        primary = next(row for row in evidence if row["evidence_id"] == primary_event["primary_evidence_id"])
        confidence = "high" if any(event["relation_confidence"] == "high" for event in events) else "medium"
        if all(event["historical_only"] for event in events):
            review_reasons.append("historical_surgery_evidence_only")
        if any(event["date_status"] != "known" for event in events):
            review_reasons.append("surgery_date_unknown_or_conflicting")
        if len(events) > 1:
            review_reasons.append("multiple_aaoca_surgery_events")
    else:
        explicit_conservative = [row for row in conservative if row["strength"] == "high"]
        latest_intent = _latest_date([*intended, *cancelled])
        latest_explicit_conservative = _latest_date(explicit_conservative)
        conservative_supersedes = bool(
            explicit_conservative
            and (not latest_intent or (latest_explicit_conservative and latest_explicit_conservative >= latest_intent))
        )
        if (intended or cancelled) and not conservative_supersedes:
            management = "intended_surgery"
            surgery_status = "unknown"
            rule = "surgical_intent_without_completion"
            candidates = [*intended, *cancelled]
            primary = max(candidates, key=_evidence_priority)
            confidence = "medium"
            review_reasons.append("completion_not_proven")
        elif conservative:
            management = "conservative"
            surgery_status = "no" if explicit_conservative else "unknown"
            rule = "explicit_nonoperative_management"
            primary = max(conservative, key=_evidence_priority)
            confidence = "high" if explicit_conservative else "medium"
            if not explicit_conservative:
                review_reasons.append("followup_or_observation_only")
        else:
            management = "unknown"
            surgery_status = "unknown"
            rule = "insufficient_management_evidence"
            primary = max(diagnostics, key=_evidence_priority) if diagnostics else None
            confidence = "low"
            review_reasons.append("no_completed_intent_or_conservative_evidence")

    if intended and conservative:
        review_reasons.append("mixed_intent_and_conservative_evidence")
        qc.append(
            {
                "patient_id": patient_id,
                "observed_management": management,
                "issue_type": "mixed_intent_and_conservative_evidence",
                "severity": "medium",
                "evidence_ids": [row["evidence_id"] for row in [*intended, *conservative]],
                "detail": "Both surgical intent and non-operative management were documented; chronology rule applied.",
            }
        )
    assigned_completed_ids = {
        evidence_id for event in events for evidence_id in _json_list(event.get("supporting_evidence_ids"))
    }
    unassigned_completed = [row for row in completed if row["evidence_id"] not in assigned_completed_ids]
    if unassigned_completed:
        review_reasons.append("completed_evidence_not_uniquely_assigned_to_event")
        qc.append(
            {
                "patient_id": patient_id,
                "observed_management": management,
                "issue_type": "completed_evidence_not_uniquely_assigned_to_event",
                "severity": "medium",
                "evidence_ids": [row["evidence_id"] for row in unassigned_completed],
                "detail": "Copied or ambiguous completion wording could not establish a distinct operation event.",
            }
        )
    if cancelled:
        review_reasons.append("cancelled_or_declined_surgery_documented")
    if any(_bool(row.get("date_requires_review")) for row in completed):
        review_reasons.append("ocr_derived_completion_or_date_evidence")
    if management == "unknown":
        qc.append(
            {
                "patient_id": patient_id,
                "observed_management": management,
                "issue_type": "management_unknown",
                "severity": "high",
                "evidence_ids": [row["evidence_id"] for row in diagnostics],
                "detail": "No reliable completed surgery, surgical intent, or explicit conservative-management evidence.",
            }
        )
    for event in events:
        for flag in _json_list(event.get("conflict_flags")):
            if flag in {"surgery_date_unknown", "section_and_surgery_date_conflict", "multiple_surgery_time_dates"}:
                qc.append(
                    {
                        "patient_id": patient_id,
                        "observed_management": management,
                        "issue_type": flag,
                        "severity": "high" if "conflict" in flag else "medium",
                        "evidence_ids": event["supporting_evidence_ids"],
                        "detail": f"Surgery event {event['surgery_event_id']} requires date review.",
                    }
                )

    # ``qc/review_queue.csv`` is a true work queue: every patient marked for
    # review below must have at least one row explaining why.  Keep separate
    # rows for distinct issues so reviewers can filter without parsing a JSON
    # list from the patient summary.
    if (intended or cancelled) and management == "intended_surgery":
        qc.append(
            {
                "patient_id": patient_id,
                "observed_management": management,
                "issue_type": "completion_not_proven",
                "severity": "high",
                "evidence_ids": [row["evidence_id"] for row in [*intended, *cancelled]],
                "detail": "Surgical intent/cancellation is documented, but completed AAOCA surgery is not proven.",
            }
        )
    if management == "conservative" and conservative and not any(row["strength"] == "high" for row in conservative):
        qc.append(
            {
                "patient_id": patient_id,
                "observed_management": management,
                "issue_type": "followup_or_observation_only",
                "severity": "medium",
                "evidence_ids": [row["evidence_id"] for row in conservative],
                "detail": "Only follow-up or historical observation supports conservative management; surgery absence remains unknown.",
            }
        )
    if events and all(_bool(event.get("historical_only")) for event in events):
        qc.append(
            {
                "patient_id": patient_id,
                "observed_management": management,
                "issue_type": "historical_surgery_evidence_only",
                "severity": "medium",
                "evidence_ids": [row["evidence_id"] for row in completed],
                "detail": "Completed surgery is supported only by historical narrative rather than a formal or postoperative record.",
            }
        )
    partial_events = [event for event in events if event.get("date_status") == "partial"]
    if partial_events:
        qc.append(
            {
                "patient_id": patient_id,
                "observed_management": management,
                "issue_type": "surgery_date_partial",
                "severity": "medium",
                "evidence_ids": [event["primary_evidence_id"] for event in partial_events],
                "detail": "At least one surgery date is supported only to month precision.",
            }
        )
    ocr_completion = [row for row in completed if _bool(row.get("date_requires_review"))]
    if ocr_completion:
        qc.append(
            {
                "patient_id": patient_id,
                "observed_management": management,
                "issue_type": "ocr_derived_completion_or_date_evidence",
                "severity": "medium",
                "evidence_ids": [row["evidence_id"] for row in ocr_completion],
                "detail": "At least one completed-surgery assertion or date came from a section already marked for date/OCR review.",
            }
        )
    if len(events) > 1:
        qc.append(
            {
                "patient_id": patient_id,
                "observed_management": management,
                "issue_type": "multiple_aaoca_surgery_events",
                "severity": "medium",
                "evidence_ids": [event["primary_evidence_id"] for event in events],
                "detail": "More than one distinct AAOCA-related surgery event was retained after deduplication.",
            }
        )

    event_dates = sorted(event["surgery_date"] for event in events if event["surgery_date"])
    procedure_types = list(dict.fromkeys(item for event in events for item in _json_list(event["procedure_types"])))
    procedure_names = list(dict.fromkeys(item for event in events for item in _json_list(event["procedure_names"])))
    event_count_status = "exact" if events and all(event["date_status"] == "known" for event in events) else "minimum" if events else "none"
    primary_values = {
        "primary_evidence_id": primary["evidence_id"] if primary else "",
        "primary_document_id": primary["document_id"] if primary else "",
        "primary_section_id": primary["section_id"] if primary else "",
        "primary_page_start": primary["page_start"] if primary else "",
        "primary_page_end": primary["page_end"] if primary else "",
        "primary_text_path": primary["text_path"] if primary else "",
        "primary_text_reference": primary["text_reference"] if primary else "",
    }
    review_reasons = list(dict.fromkeys(review_reasons))
    row = {
        "patient_id": patient_id,
        "aaoca_judgment": "yes",
        "aaoca_judgment_source": judgment_source,
        "observed_management": management,
        "actual_aaoca_surgery": surgery_status,
        "management_confidence": confidence,
        "management_rule": rule,
        "n_surgery_events": len(events),
        "surgery_event_count_status": event_count_status,
        "first_surgery_date": event_dates[0] if event_dates else "",
        "last_surgery_date": event_dates[-1] if event_dates else "",
        "surgery_dates": event_dates,
        "surgery_date_precisions": [event["surgery_date_precision"] for event in events],
        "surgery_event_ids": [event["surgery_event_id"] for event in events],
        "procedure_types": procedure_types,
        "procedure_names": procedure_names,
        "has_completed_surgery_evidence": bool(completed),
        "has_surgical_intent_evidence": bool(intended),
        "has_cancelled_or_declined_evidence": bool(cancelled),
        "has_conservative_evidence": bool(conservative),
        "has_diagnostic_procedure_evidence": bool(diagnostics),
        "has_unrelated_surgery_evidence": bool(unrelated),
        **primary_values,
        "n_management_evidence_rows": len(evidence),
        "review_required": bool(review_reasons),
        "review_reasons": review_reasons,
    }
    return row, qc


def aggregate_management(
    selection: list[dict], evidence: list[dict], events: list[dict]
) -> tuple[list[dict], list[dict]]:
    evidence_by_patient: dict[str, list[dict]] = defaultdict(list)
    events_by_patient: dict[str, list[dict]] = defaultdict(list)
    for row in evidence:
        evidence_by_patient[row["patient_id"]].append(row)
    for row in events:
        events_by_patient[row["patient_id"]].append(row)
    summaries: list[dict] = []
    qc: list[dict] = []
    for selected in selection:
        if not _bool(selected["included_for_management"]):
            continue
        row, issues = _patient_summary(
            selected["patient_id"],
            selected["judgment_source"],
            evidence_by_patient[selected["patient_id"]],
            events_by_patient[selected["patient_id"]],
        )
        summaries.append(row)
        qc.extend(issues)
    return summaries, qc


def _package_readme() -> str:
    return """# AAOCA management deterministic output\n\nThis restricted local directory contains patient-derived evidence excerpts.\nDo not commit, upload, or send it to an external service.\n\n- `management_summary.csv`: one row per included `AAOCA=yes` patient.\n- `surgery_events.csv`: deduplicated AAOCA-related completed operations.\n- `management_evidence.csv`: every assertion with exact source and character span.\n- `cohort_selection.csv`: how the AAOCA review result selected/excluded patients.\n- `qc/review_queue.csv`: unknown, conflicting, mixed-stage, and date-review cases.\n- `run_metadata.json`: ruleset, source hashes, counts, and privacy/runtime receipt.\n\n`observed_management=surgery` requires completed AAOCA-operation evidence. A\nplanned procedure, consent, preoperative discussion, catheterisation, or coronary\nangiography cannot establish surgery. `conservative` requires affirmative\nnon-operative evidence; missing surgery documentation remains `unknown`.\n"""


def write_management_package(
    run_root: Path,
    relevance_root: Path,
    output: Path,
    extractor: ManagementEvidenceExtractor | None = None,
) -> dict:
    run_root = run_root.resolve()
    relevance_root = relevance_root.resolve()
    output = output.resolve()
    selection, cohort_receipt = resolve_aaoca_cohort(run_root, relevance_root)
    patient_ids = {row["patient_id"] for row in selection if row["included_for_management"]}
    sections = load_sections(run_root, patient_ids)
    evidence = extract_management_evidence(sections, extractor)
    events = build_surgery_events(evidence)
    summaries, qc = aggregate_management(selection, evidence, events)

    write_csv(output / "cohort_selection.csv", selection, SELECTION_FIELDS)
    write_csv(output / "management_evidence.csv", evidence, EVIDENCE_FIELDS)
    write_csv(output / "surgery_events.csv", events, EVENT_FIELDS)
    write_csv(output / "management_summary.csv", summaries, SUMMARY_FIELDS)
    write_csv(output / "qc" / "review_queue.csv", qc, QC_FIELDS)
    write_text(output / "README.md", _package_readme())

    code_path = Path(__file__)
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "method": "deterministic_rules",
        "source_run": str(run_root),
        "source_relevance_review": str(relevance_root),
        "contains_clinical_excerpts": True,
        "network_processing": False,
        "llm_invoked": False,
        "cohort": cohort_receipt,
        "counts": {
            "included_patients": len(summaries),
            "sections_scanned": len(sections),
            "management_evidence_rows": len(evidence),
            "surgery_events": len(events),
            "review_queue_rows": len(qc),
            "management_statuses": dict(Counter(row["observed_management"] for row in summaries)),
            "actual_aaoca_surgery": dict(Counter(row["actual_aaoca_surgery"] for row in summaries)),
            "patients_with_multiple_surgery_events": sum(int(row["n_surgery_events"]) > 1 for row in summaries),
        },
        "source_hashes": {
            "run_metadata": sha256_file(run_root / "run_metadata.json"),
            "patient_manifest": sha256_file(run_root / "patient_manifest.csv"),
            "section_index": sha256_file(run_root / "section_index.csv"),
            "relevance_metadata": sha256_file(relevance_root / "run_metadata.json"),
            "relevance_cases": sha256_file(relevance_root / "exception_cases.csv"),
        },
        "code_sha256": sha256_file(code_path),
    }
    write_json(output / "run_metadata.json", metadata)
    validation = validate_management_package(output, run_root, relevance_root)
    if validation["validation_status"] != "passed":
        raise ValueError(f"Generated management package failed validation: {validation['errors'][:3]}")
    return {**metadata, "validation": validation}


def validate_management_package(
    output: Path,
    run_root: Path | None = None,
    relevance_root: Path | None = None,
) -> dict:
    output = output.resolve()
    errors: list[dict] = []
    warnings: list[dict] = []
    required = {
        "selection": output / "cohort_selection.csv",
        "summary": output / "management_summary.csv",
        "evidence": output / "management_evidence.csv",
        "events": output / "surgery_events.csv",
        "qc": output / "qc" / "review_queue.csv",
        "metadata": output / "run_metadata.json",
    }
    for name, path in required.items():
        if not path.is_file():
            errors.append({"code": "missing_artifact", "artifact": name, "path": str(path)})
    if errors:
        return {"validation_status": "failed", "error_count": len(errors), "warning_count": 0, "errors": errors, "warnings": []}

    selection = _read_csv(required["selection"])
    summaries = _read_csv(required["summary"])
    evidence = _read_csv(required["evidence"])
    events = _read_csv(required["events"])
    qc = _read_csv(required["qc"])
    metadata = json.loads(required["metadata"].read_text(encoding="utf-8"))
    selected_ids = {row["patient_id"] for row in selection if _bool(row["included_for_management"])}
    summary_ids = [row["patient_id"] for row in summaries]
    if len(summary_ids) != len(set(summary_ids)):
        errors.append({"code": "duplicate_summary_patient"})
    if set(summary_ids) != selected_ids:
        errors.append({"code": "summary_selection_mismatch"})

    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    if len(evidence_by_id) != len(evidence):
        errors.append({"code": "duplicate_evidence_id"})
    event_by_id = {row["surgery_event_id"]: row for row in events}
    if len(event_by_id) != len(events):
        errors.append({"code": "duplicate_surgery_event_id"})
    if any(row["patient_id"] not in selected_ids for row in evidence + events):
        errors.append({"code": "excluded_patient_in_management_artifact"})
    if any(row["patient_id"] not in selected_ids for row in qc):
        errors.append({"code": "excluded_patient_in_qc_artifact"})

    summary_by_patient = {row["patient_id"]: row for row in summaries}
    event_counts = Counter(row["patient_id"] for row in events)
    for row in summaries:
        patient_id = row["patient_id"]
        status = row["observed_management"]
        if status not in MANAGEMENT_VALUES:
            errors.append({"code": "invalid_management_status", "patient_id": patient_id, "value": status})
        if row["actual_aaoca_surgery"] not in SURGERY_STATUS_VALUES:
            errors.append({"code": "invalid_surgery_status", "patient_id": patient_id})
        if (status == "surgery") != (row["actual_aaoca_surgery"] == "yes"):
            errors.append({"code": "management_surgery_status_mismatch", "patient_id": patient_id})
        if int(row["n_surgery_events"] or 0) != event_counts[patient_id]:
            errors.append({"code": "summary_event_count_mismatch", "patient_id": patient_id})
        if status == "surgery" and event_counts[patient_id] == 0:
            errors.append({"code": "surgery_without_event", "patient_id": patient_id})
        if status != "surgery" and event_counts[patient_id]:
            errors.append({"code": "event_for_nonsurgery_patient", "patient_id": patient_id})
        if status == "conservative" and not _bool(row["has_conservative_evidence"]):
            errors.append({"code": "conservative_without_evidence", "patient_id": patient_id})
        if status == "intended_surgery" and not (
            _bool(row["has_surgical_intent_evidence"]) or _bool(row["has_cancelled_or_declined_evidence"])
        ):
            errors.append({"code": "intent_without_evidence", "patient_id": patient_id})
        patient_evidence = [item for item in evidence if item["patient_id"] == patient_id]
        if int(row["n_management_evidence_rows"] or 0) != len(patient_evidence):
            errors.append({"code": "summary_evidence_count_mismatch", "patient_id": patient_id})
        primary_id = row.get("primary_evidence_id", "")
        if primary_id and (
            primary_id not in evidence_by_id or evidence_by_id[primary_id]["patient_id"] != patient_id
        ):
            errors.append({"code": "summary_primary_evidence_invalid", "patient_id": patient_id})

    for event in events:
        surgery_date = event.get("surgery_date", "")
        precision = event.get("surgery_date_precision", "")
        date_status = event.get("date_status", "")
        valid_date_shape = (
            (not surgery_date and precision == "unknown" and date_status == "unknown")
            or (bool(re.fullmatch(r"\d{4}-\d{2}", surgery_date)) and precision == "month" and date_status == "partial")
            or (
                bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", surgery_date))
                and precision == "day"
                and date_status in {"known", "conflict"}
            )
        )
        if not valid_date_shape:
            errors.append({"code": "invalid_event_date_state", "surgery_event_id": event["surgery_event_id"]})
        ids = _json_list(event["supporting_evidence_ids"])
        if not ids or event["primary_evidence_id"] not in ids:
            errors.append({"code": "invalid_event_evidence_list", "surgery_event_id": event["surgery_event_id"]})
        for evidence_id in ids:
            source = evidence_by_id.get(evidence_id)
            if not source:
                errors.append({"code": "event_missing_evidence", "surgery_event_id": event["surgery_event_id"], "evidence_id": evidence_id})
            elif source["patient_id"] != event["patient_id"] or source["assertion"] != "completed" or not _bool(source["counts_as_aaoca_surgery"]):
                errors.append({"code": "event_invalid_evidence", "surgery_event_id": event["surgery_event_id"], "evidence_id": evidence_id})

    qc_patient_ids = {row["patient_id"] for row in qc}
    for row in summaries:
        if _bool(row.get("review_required")) and row["patient_id"] not in qc_patient_ids:
            errors.append({"code": "review_required_patient_missing_from_qc", "patient_id": row["patient_id"]})
    for row in qc:
        for evidence_id in _json_list(row.get("evidence_ids")):
            source = evidence_by_id.get(evidence_id)
            if not source or source["patient_id"] != row["patient_id"]:
                errors.append({"code": "qc_evidence_invalid", "patient_id": row["patient_id"], "evidence_id": evidence_id})

    if run_root:
        run_root = run_root.resolve()
        source_sections = {section["section_id"]: section for section in load_sections(run_root, selected_ids)}
        for row in evidence:
            section = source_sections.get(row["section_id"])
            if not section:
                errors.append({"code": "evidence_section_missing", "evidence_id": row["evidence_id"]})
                continue
            start, end = int(row["char_start"]), int(row["char_end"])
            text = section.get("text", "")
            if start < 0 or end < start or end > len(text) or text[start:end] != row["evidence_text"]:
                errors.append({"code": "evidence_span_mismatch", "evidence_id": row["evidence_id"]})
        expected_hashes = {
            "run_metadata": sha256_file(run_root / "run_metadata.json"),
            "patient_manifest": sha256_file(run_root / "patient_manifest.csv"),
            "section_index": sha256_file(run_root / "section_index.csv"),
        }
        for key, value in expected_hashes.items():
            if metadata.get("source_hashes", {}).get(key) != value:
                errors.append({"code": "source_hash_mismatch", "source": key})
    if relevance_root:
        relevance_root = relevance_root.resolve()
        expected = {
            "relevance_metadata": sha256_file(relevance_root / "run_metadata.json"),
            "relevance_cases": sha256_file(relevance_root / "exception_cases.csv"),
        }
        for key, value in expected.items():
            if metadata.get("source_hashes", {}).get(key) != value:
                errors.append({"code": "source_hash_mismatch", "source": key})

    counts = metadata.get("counts", {})
    actual_statuses = dict(Counter(row["observed_management"] for row in summaries))
    if (
        counts.get("included_patients") != len(summaries)
        or counts.get("management_statuses") != actual_statuses
        or counts.get("management_evidence_rows") != len(evidence)
        or counts.get("surgery_events") != len(events)
        or counts.get("review_queue_rows") != len(qc)
    ):
        errors.append({"code": "metadata_count_mismatch"})
    return {
        "validation_status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "patients": len(summaries),
        "evidence_rows": len(evidence),
        "surgery_events": len(events),
        "management_statuses": actual_statuses,
        "errors": errors,
        "warnings": warnings,
    }
