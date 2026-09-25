"""Find patient-level AAOCA relevance exceptions for focused human review.

The source cohort was already screened by the hospital and the observed corpus
is overwhelmingly AAOCA/coronary-origin related.  This module therefore does
not ask reviewers to relabel every patient.  It extracts provenance-bearing
signals, treats the ordinary high-evidence cases as the screened default, and
exports only cases where data coverage, assertion state, anatomy, or scope is
unusual enough to warrant review.

The deterministic extractor is deliberately separate from patient aggregation.
A future *local* LLM middleware may implement ``AaocaEvidenceExtractor`` and
emit the same ``EvidenceSignal`` contract without changing review/finalization
semantics or overwriting source text.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Protocol

from .io_utils import sha256_file, write_csv, write_json, write_text


RULESET_VERSION = "aaoca_exception_rules_v1"

CLINICAL_TYPES = {
    "admission",
    "progress",
    "consultation",
    "discharge",
    "outpatient",
    "procedure",
    "surgery_related",  # compatibility with the earlier v0.1 snapshot
    "follow_up",
    "ultrasound",
}

UNCERTAIN_RE = re.compile(r"可能|疑似|待排|待查|不能除外|不除外|考虑|显示不清|[?？]")
EXPLICIT_EXCLUSION_RE = re.compile(
    r"(?:排除|除外|不支持|未提示|未发现|未见)(?:.{0,16})"
    r"(?:AAOCA|冠(?:状动脉|脉)(?:起源异常|异常起源|异常主动脉起源))",
    re.I,
)
NORMAL_ORIGIN_RE = re.compile(
    r"(?P<subject>左右冠(?:状动脉|脉)|右冠(?:状动脉|脉)?|左冠(?:状动脉|脉)?|RCA|LCA|LMCA)"
    r".{0,10}(?:起源|开[口又]).{0,8}(?:正常|未见(?:明显)?异常)",
    re.I,
)

# The origin expression is intentionally narrow.  A broad proximity rule would
# misread "abnormal origin, coursing behind the pulmonary artery" as origin
# *from* the pulmonary artery.
ORIGIN_FACT_RE = re.compile(
    r"(?P<subject>左右冠(?:状动脉|脉)|左、右冠(?:状动脉|脉)|"
    r"右冠状动脉|右冠脉|右冠|RCA|"
    r"左冠状动脉|左冠脉|左冠|左主干|LCA|LMCA|LM|"
    r"回旋支|左回旋支|LCX|前降支|左前降支|LAD)"
    r"[^。；;:\n]{0,18}?(?:异常)?(?:起源于?|起自|发自|源自|开[口又]于?|来自)\s*"
    r"(?P<origin>左冠状动脉窦|右冠状动脉窦|左冠窦|右冠窦|左瓣窦|右瓣窦|"
    r"无冠窦|肺动脉主干|主肺动脉|肺动脉|升主动脉|左主干|左冠状动脉|"
    r"左冠脉|左冠|左前降支|前降支|LAD|右冠状动脉|右冠脉|右冠)",
    re.I,
)
ENGLISH_ORIGIN_RE = re.compile(
    r"(?P<subject>RCA|LCA|LMCA|LM|LCX|LAD).{0,24}?(?:anom\.?\s*)?"
    r"(?:origin(?:ates|ating)?|from).{0,12}(?P<origin>left|right|noncoronary)\s*(?:coronary\s*)?sinus",
    re.I,
)

RULES: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
    (
        "aaoca_literal",
        "aaoca_term",
        re.compile(r"(?<![A-Z])(?:AAOCA|AOCA|ACAOS)(?![A-Z])", re.I),
        "decisive",
    ),
    (
        "formal_origin_anomaly",
        "formal_origin_anomaly",
        re.compile(
            r"冠(?:状动脉|脉)(?:异常主动脉起源|主动脉异常起源|起源异常|异常起源|异位起源)"
            r"|冠(?:状动脉|脉)(?:起源|开[口又])\s*(?:畸形|异常)"
        ),
        "decisive",
    ),
    (
        "generic_coronary_anomaly",
        "generic_coronary_anomaly",
        re.compile(r"(?:先天性)?冠(?:状动脉|脉)(?:畸形|异常)(?:-其他)?"),
        "supporting",
    ),
    (
        "pulmonary_origin_acronym",
        "pulmonary_coronary_origin",
        re.compile(r"(?<![A-Z])(?:ALCAPA|ARCAPA|ACAPA)(?![A-Z])", re.I),
        "decisive",
    ),
    (
        "single_coronary",
        "single_coronary_or_complex_chd",
        re.compile(r"单(?:一|支)?(?:左|右)?冠(?:状动脉|脉)|冠(?:状动脉|脉)[(（]单支[)）]"),
        "decisive",
    ),
    (
        "high_origin",
        "high_coronary_origin",
        re.compile(r"(?:左|右)?冠(?:状动脉|脉).{0,10}高位(?:起源|开[口又])|(?:左|右)?冠(?:状动脉|脉)高位"),
        "supporting",
    ),
    (
        "high_risk_course",
        "intramural_or_interarterial_course",
        re.compile(
            r"(?:左|右)?冠(?:状动脉|脉|冠).{0,40}(?:壁内走[行形]|壁间走[行形]|主[-—]?肺动脉.{0,8}(?:间|之间))"
            r"|(?:壁内走[行形]|壁间走[行形]).{0,24}(?:冠状动脉|冠脉|RCA|LCA)",
            re.I,
        ),
        "decisive",
    ),
    (
        "aaoca_repair",
        "aaoca_specific_procedure",
        re.compile(
            r"冠(?:状动脉|脉)(?:异常起源|起源异常)?(?:纠治|矫正|修补|开[口又]成形|移植|再植|去顶)(?:术)?"
            r"|(?:左|右)?冠(?:状动脉|冠脉)去顶|(?:AAOCA|AOCA).{0,10}(?:矫治|纠治|修补)",
            re.I,
        ),
        "decisive",
    ),
    (
        "targeted_workup",
        "targeted_coronary_workup",
        re.compile(
            r"(?:冠脉CTA|冠状动脉CTA|CCTA|冠脉造影|冠状动脉造影|多根导管冠状动脉造影)"
            r"|(?:心脏|胸主动脉)(?:增强)?CT.{0,50}(?:冠(?:状动脉|脉).{0,12}(?:起源|开[口又]))",
            re.I,
        ),
        "context",
    ),
    (
        "explicit_exclusion",
        "explicit_exclusion",
        EXPLICIT_EXCLUSION_RE,
        "decisive",
    ),
    (
        "normal_origin",
        "normal_coronary_origin",
        NORMAL_ORIGIN_RE,
        "context",
    ),
)

POSITIVE_CATEGORIES = {
    "aaoca_term",
    "formal_origin_anomaly",
    "specific_abnormal_origin",
    "pulmonary_coronary_origin",
    "coronary_branch_origin",
    "generic_coronary_anomaly",
    "single_coronary_or_complex_chd",
    "high_coronary_origin",
    "intramural_or_interarterial_course",
    "aaoca_specific_procedure",
    "explicit_exclusion",  # exclusion proves the direction was considered
}
DETAIL_CATEGORIES = {
    "aaoca_term",
    "specific_abnormal_origin",
    "pulmonary_coronary_origin",
    "coronary_branch_origin",
    "single_coronary_or_complex_chd",
    "intramural_or_interarterial_course",
    "aaoca_specific_procedure",
    "explicit_exclusion",
}

CASE_FIELDS = [
    "patient_id",
    "inpatient_id",
    "outpatient_id",
    "name",
    "automatic_aaoca_judgment",
    "exception_reasons",
    "review_priority",
    "automatic_rationale",
    "relevant_evidence_summary",
    "n_evidence_rows",
    "n_evidence_sections",
    "n_clinical_sections",
    "n_pdf",
    "patient_parse_status",
    "evidence_text_sources",
    "review_status",
    "final_aaoca_judgment",
    "reviewer_notes",
]

EVIDENCE_FIELDS = [
    "patient_id",
    "evidence_id",
    "rule_id",
    "category",
    "assertion",
    "strength",
    "target",
    "origin",
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
    "evidence_text",
    "source_pdf",
    "text_path",
    "text_reference",
]


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _excerpt(text: str, start: int, end: int, radius: int = 110) -> str:
    return _compact(text[max(0, start - radius): min(len(text), end + radius)])


def _assertion(excerpt: str, category: str) -> str:
    if category in {"normal_coronary_origin", "explicit_exclusion"}:
        return "normal_or_excluded"
    return "uncertain" if UNCERTAIN_RE.search(excerpt) else "affirmed"


def _subject(value: str) -> str:
    upper = value.upper()
    if "左右" in value or "左、右" in value:
        return "both"
    if "回旋" in value or upper == "LCX":
        return "left_circumflex"
    if "前降" in value or upper == "LAD":
        return "left_anterior_descending"
    if "右" in value or upper == "RCA":
        return "right_coronary"
    if "左" in value or upper in {"LCA", "LM", "LMCA"}:
        return "left_coronary"
    return "coronary_unspecified"


def _origin(value: str) -> str:
    lower = value.lower()
    if "肺动脉" in value:
        return "pulmonary_artery"
    if "无冠" in value or "noncoronary" in lower:
        return "noncoronary_sinus"
    if "左冠窦" in value or "左瓣窦" in value or lower == "left" or "left" in lower and "sinus" in lower:
        return "left_sinus"
    if "右冠窦" in value or "右瓣窦" in value or lower == "right" or "right" in lower and "sinus" in lower:
        return "right_sinus"
    if "升主动脉" in value:
        return "ascending_aorta"
    if "前降" in value or value.upper() == "LAD":
        return "left_anterior_descending"
    if "左主干" in value:
        return "left_main"
    if value in {"左冠状动脉", "左冠脉"}:
        return "left_coronary"
    if value == "左冠":
        # In this corpus "右冠起自左冠" is usually shorthand for the left
        # coronary sinus; explicit artery/branch wording remains a branch fact.
        return "left_sinus"
    if value in {"右冠状动脉", "右冠脉"}:
        return "right_coronary"
    if value == "右冠":
        return "right_sinus"
    return "other"


def _expected_origin(subject: str, origin: str) -> bool:
    return (subject == "right_coronary" and origin == "right_sinus") or (
        subject in {"left_coronary", "left_circumflex", "left_anterior_descending"}
        and origin == "left_sinus"
    )


@dataclass(frozen=True)
class EvidenceSignal:
    patient_id: str
    evidence_id: str
    rule_id: str
    category: str
    assertion: str
    strength: str
    target: str
    origin: str
    document_id: str
    section_id: str
    section_type: str
    section_subtype: str
    section_date: str
    page_start: int | str
    page_end: int | str
    text_source: str
    date_requires_review: bool
    parse_status: str
    evidence_text: str
    source_pdf: str
    text_path: str
    text_reference: str

    def row(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OriginFact:
    patient_id: str
    subject: str
    origin: str
    assertion: str
    section_id: str
    evidence_id: str


class AaocaEvidenceExtractor(Protocol):
    """Stable middleware seam for deterministic rules or a future local LLM."""

    method: str
    method_version: str

    def extract(self, section: dict) -> tuple[list[EvidenceSignal], list[OriginFact]]:
        """Return evidence without modifying the provenance-bearing section."""
        ...


class DeterministicAaocaEvidenceExtractor:
    method = "deterministic_rules"
    method_version = RULESET_VERSION

    @staticmethod
    def _signal(
        section: dict,
        rule_id: str,
        category: str,
        strength: str,
        match: re.Match[str],
        *,
        target: str = "coronary_unspecified",
        origin: str = "",
    ) -> EvidenceSignal:
        text = section.get("text", "")
        excerpt = _excerpt(text, match.start(), match.end())
        assertion_excerpt = _excerpt(text, match.start(), match.end(), radius=35)
        identity = "|".join(
            [
                section.get("patient_id", ""),
                section.get("document_id", ""),
                section.get("section_id", ""),
                rule_id,
                str(match.start()),
                str(match.end()),
            ]
        )
        return EvidenceSignal(
            patient_id=section.get("patient_id", ""),
            evidence_id="ev_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
            rule_id=rule_id,
            category=category,
            assertion=_assertion(assertion_excerpt, category),
            strength=strength,
            target=target,
            origin=origin,
            document_id=section.get("document_id", ""),
            section_id=section.get("section_id", ""),
            section_type=section.get("section_type", ""),
            section_subtype=section.get("section_subtype", ""),
            section_date=section.get("section_date", ""),
            page_start=section.get("page_start", ""),
            page_end=section.get("page_end", ""),
            text_source=section.get("text_source", ""),
            date_requires_review=bool(section.get("date_requires_review")),
            parse_status=section.get("parse_status", ""),
            evidence_text=excerpt,
            source_pdf=section.get("source_pdf", ""),
            text_path=section.get("text_path", ""),
            text_reference=section.get("text_reference", ""),
        )

    def extract(self, section: dict) -> tuple[list[EvidenceSignal], list[OriginFact]]:
        text = section.get("text", "")
        signals: list[EvidenceSignal] = []
        facts: list[OriginFact] = []

        # Two examples per rule/section keep the review artifact concise while
        # preserving independent sections and rule categories.
        for rule_id, category, pattern, strength in RULES:
            for match in list(pattern.finditer(text))[:2]:
                target = _subject(match.groupdict().get("subject", "")) if "subject" in match.groupdict() else "coronary_unspecified"
                signals.append(self._signal(section, rule_id, category, strength, match, target=target))

        seen_facts: set[tuple[str, str, int]] = set()
        for rule_id, pattern in (("specific_origin", ORIGIN_FACT_RE), ("english_specific_origin", ENGLISH_ORIGIN_RE)):
            for match in pattern.finditer(text):
                subject = _subject(match.group("subject"))
                origin = _origin(match.group("origin"))
                expanded_subjects = ["left_coronary", "right_coronary"] if subject == "both" else [subject]
                for expanded in expanded_subjects:
                    if expanded == "right_coronary" and origin == "right_coronary":
                        origin = "right_sinus"
                    elif expanded in {"left_coronary", "left_circumflex", "left_anterior_descending"} and origin == "left_coronary":
                        origin = "left_sinus"
                    key = (expanded, origin, match.start())
                    if key in seen_facts:
                        continue
                    seen_facts.add(key)
                    if origin == "pulmonary_artery":
                        category, strength = "pulmonary_coronary_origin", "decisive"
                    elif origin in {"left_main", "left_anterior_descending", "left_coronary", "right_coronary"}:
                        category, strength = "coronary_branch_origin", "decisive"
                    elif _expected_origin(expanded, origin):
                        # Expected anatomy is retained as a fact for conflict
                        # analysis, but is not positive AAOCA evidence by itself.
                        category, strength = "expected_coronary_origin", "context"
                    else:
                        category, strength = "specific_abnormal_origin", "decisive"
                    signal = self._signal(
                        section,
                        rule_id,
                        category,
                        strength,
                        match,
                        target=expanded,
                        origin=origin,
                    )
                    signals.append(signal)
                    facts.append(
                        OriginFact(
                            patient_id=signal.patient_id,
                            subject=expanded,
                            origin=origin,
                            assertion=signal.assertion,
                            section_id=signal.section_id,
                            evidence_id=signal.evidence_id,
                        )
                    )

        # Stable de-duplication in case a compact phrase satisfies two anatomy
        # alternatives with the same semantic result.
        unique: dict[tuple[str, str, str, str, str], EvidenceSignal] = {}
        for signal in signals:
            key = (signal.section_id, signal.rule_id, signal.category, signal.target, signal.origin)
            unique.setdefault(key, signal)
        return list(unique.values()), facts


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_run(run_root: Path) -> tuple[list[dict], dict[str, dict], dict[str, list[dict]]]:
    """Load one completed pipeline snapshot without opening source PDFs."""
    run_root = Path(run_root).resolve()
    metadata = json.loads((run_root / "run_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("status") != "complete":
        raise ValueError("AAOCA exception review requires a complete pipeline run")
    summary = json.loads((run_root / "qc" / "cohort_summary.json").read_text(encoding="utf-8"))
    if summary.get("source_hash_verification") != "passed":
        raise ValueError("AAOCA exception review requires passed source hash verification")

    manifest = _read_csv(run_root / "patient_manifest.csv")
    linkage = {row["patient_id"]: row for row in _read_csv(run_root / "private" / "patient_linkage.csv")}
    by_patient: dict[str, list[dict]] = defaultdict(list)
    for path in sorted((run_root / "sections").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for section in payload.get("sections", []):
            if section.get("patient_id"):
                by_patient[section["patient_id"]].append(section)
    if {row["patient_id"] for row in manifest} - set(linkage):
        raise ValueError("Patient linkage is incomplete")
    return manifest, linkage, by_patient


def _origin_conflicts(facts: list[OriginFact]) -> list[str]:
    origins: dict[str, set[str]] = defaultdict(set)
    for fact in facts:
        if fact.assertion != "affirmed":
            continue
        # "Ascending aorta" is compatible with a high ostium above a named
        # sinus. "Other" is not precise enough to establish a contradiction.
        if fact.origin not in {"ascending_aorta", "other"}:
            origins[fact.subject].add(fact.origin)
    conflicts = [subject for subject, values in origins.items() if len(values) > 1]
    return sorted(conflicts)


def _evidence_summary(signals: list[EvidenceSignal], limit: int = 3) -> str:
    priority = {"decisive": 0, "supporting": 1, "context": 2}
    selected = sorted(
        signals,
        key=lambda signal: (
            priority.get(signal.strength, 9),
            signal.assertion != "affirmed",
            signal.section_date or "9999-99-99",
            signal.section_id,
        ),
    )[:limit]
    return " || ".join(f"[{s.category}/{s.assertion}] {s.evidence_text}" for s in selected)


def _select_review_evidence(signals: list[EvidenceSignal], limit: int = 12) -> list[EvidenceSignal]:
    """Keep a small, semantically diverse evidence set for each exception."""
    category_priority = {
        "specific_abnormal_origin": 0,
        "pulmonary_coronary_origin": 1,
        "coronary_branch_origin": 2,
        "normal_coronary_origin": 3,
        "expected_coronary_origin": 4,
        "single_coronary_or_complex_chd": 5,
        "aaoca_term": 6,
        "formal_origin_anomaly": 7,
        "aaoca_specific_procedure": 8,
        "intramural_or_interarterial_course": 9,
        "high_coronary_origin": 10,
        "explicit_exclusion": 11,
        "generic_coronary_anomaly": 12,
        "targeted_coronary_workup": 13,
    }
    ordered = sorted(
        signals,
        key=lambda signal: (
            category_priority.get(signal.category, 99),
            signal.assertion != "affirmed",
            signal.section_date or "9999-99-99",
            signal.section_id,
        ),
    )
    selected: list[EvidenceSignal] = []
    per_semantic_key: Counter[tuple[str, str, str, str]] = Counter()
    for signal in ordered:
        key = (signal.category, signal.assertion, signal.target, signal.origin)
        if per_semantic_key[key] >= 2:
            continue
        per_semantic_key[key] += 1
        selected.append(signal)
        if len(selected) >= limit:
            break
    return selected


def assess_patients(
    run_root: Path,
    extractor: AaocaEvidenceExtractor | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """Return exception cases, their evidence, and PHI-free aggregate metadata."""
    extractor = extractor or DeterministicAaocaEvidenceExtractor()
    manifest, linkage, by_patient = load_run(run_root)
    all_assessments: list[dict] = []
    evidence_by_patient: dict[str, list[EvidenceSignal]] = defaultdict(list)
    facts_by_patient: dict[str, list[OriginFact]] = defaultdict(list)

    for patient in manifest:
        patient_id = patient["patient_id"]
        sections = by_patient.get(patient_id, [])
        for section in sections:
            signals, facts = extractor.extract(section)
            evidence_by_patient[patient_id].extend(signals)
            facts_by_patient[patient_id].extend(facts)

        signals = evidence_by_patient[patient_id]
        positive = [s for s in signals if s.category in POSITIVE_CATEGORIES]
        affirmed = [s for s in positive if s.assertion == "affirmed"]
        uncertain = [s for s in positive if s.assertion == "uncertain"]
        meaningful_sections = {s.section_id for s in positive}
        clinical_positive = [s for s in positive if s.section_type in CLINICAL_TYPES]
        clinical_sections = [s for s in sections if s.get("section_type") in CLINICAL_TYPES]
        clinical_chars = sum(len(s.get("text", "")) for s in clinical_sections)
        normal_signals = [s for s in signals if s.category == "normal_coronary_origin"]
        categories = {s.category for s in positive}

        if positive and clinical_positive:
            judgment = "yes"
        elif positive:
            # A diagnosis copied only in browser chrome/laboratory headers does
            # not establish a meaningful diagnostic process on its own.
            judgment = "uncertain"
        elif clinical_chars >= 1000 and clinical_sections:
            judgment = "no"
        else:
            judgment = "uncertain"

        reasons: list[str] = []
        if int(patient.get("n_pdf") or 0) == 0 or not sections:
            reasons.append("missing_source_documentation")
        if positive and not clinical_positive:
            reasons.append("evidence_only_in_nonclinical_or_laboratory_content")
        if (
            positive
            and len(meaningful_sections) == 1
            and (not clinical_positive or (uncertain and not affirmed) or not categories.intersection(DETAIL_CATEGORIES))
        ):
            reasons.append("single_evidence_section")
        if positive and uncertain and not affirmed:
            reasons.append("tentative_evidence_only")
        if judgment == "no":
            reasons.append("no_meaningful_aaoca_evidence_in_adequate_record")
        elif judgment == "uncertain" and not reasons:
            reasons.append("insufficient_evidence_for_reliable_judgment")

        conflicts = _origin_conflicts(facts_by_patient[patient_id])
        if conflicts:
            reasons.append("conflicting_coronary_origin_descriptions")
        normal_targets: set[str] = set()
        for signal in normal_signals:
            if signal.target == "both":
                normal_targets.update({"left_coronary", "right_coronary"})
            else:
                normal_targets.add(signal.target)
        abnormal_targets = {
            fact.subject
            for fact in facts_by_patient[patient_id]
            if fact.assertion == "affirmed"
            and not _expected_origin(fact.subject, fact.origin)
            and fact.origin not in {"ascending_aorta", "other"}
        }
        normal_and_abnormal = bool(normal_targets & abnormal_targets)
        if normal_and_abnormal:
            reasons.append("normal_and_abnormal_origin_same_vessel")
        if "pulmonary_coronary_origin" in categories:
            reasons.append("pulmonary_origin_scope_boundary")
        if "single_coronary_or_complex_chd" in categories or "coronary_branch_origin" in categories:
            reasons.append("single_coronary_or_complex_chd_scope_boundary")
        if (
            "high_coronary_origin" in categories
            and not categories.intersection(
                {
                    "aaoca_term",
                    "specific_abnormal_origin",
                    "pulmonary_coronary_origin",
                    "coronary_branch_origin",
                    "intramural_or_interarterial_course",
                    "aaoca_specific_procedure",
                }
            )
        ):
            reasons.append("high_origin_without_more_specific_anatomy")
        if normal_signals and positive and not facts_by_patient[patient_id]:
            reasons.append("normal_origin_and_nonspecific_positive_label")
        if positive and not categories.intersection(DETAIL_CATEGORIES) and len(meaningful_sections) <= 2:
            reasons.append("sparse_nonspecific_label")
        if positive and all(s.text_source.startswith("local_ocr") for s in positive) and len(meaningful_sections) <= 2:
            reasons.append("sparse_ocr_only_evidence")

        # Preserve order while removing overlap between closely related checks.
        reasons = list(dict.fromkeys(reasons))
        linkage_row = linkage[patient_id]
        if judgment != "yes":
            priority = "required"
        elif any("conflict" in reason or "scope_boundary" in reason for reason in reasons):
            priority = "high"
        else:
            priority = "medium"
        rationale = {
            "yes": "文书中存在有意义的 AAOCA 或冠状动脉起源异常诊疗证据，但下列例外仍需确认。",
            "no": "现有临床文书较充分，但规则未找到 AAOCA 或相应冠脉异常进入诊疗过程的证据。",
            "uncertain": "现有资料或证据位置不足以可靠确认 AAOCA 是否真正进入诊疗过程。",
        }[judgment]
        all_assessments.append(
            {
                "patient_id": patient_id,
                "inpatient_id": linkage_row.get("inpatient_id", ""),
                "outpatient_id": linkage_row.get("outpatient_id", ""),
                "name": linkage_row.get("name", ""),
                "automatic_aaoca_judgment": judgment,
                "exception_reasons": reasons,
                "review_priority": priority,
                "automatic_rationale": rationale,
                "relevant_evidence_summary": _evidence_summary(positive or normal_signals),
                "n_evidence_rows": len(positive),
                "n_evidence_sections": len(meaningful_sections),
                "n_clinical_sections": len(clinical_sections),
                "n_pdf": int(patient.get("n_pdf") or 0),
                "patient_parse_status": patient.get("parse_status", ""),
                "evidence_text_sources": sorted({s.text_source for s in positive if s.text_source}),
                "review_status": "not_reviewed",
                "final_aaoca_judgment": "",
                "reviewer_notes": "",
                "_reasons": reasons,
            }
        )

    exceptions = [row for row in all_assessments if row["_reasons"]]
    exceptions.sort(
        key=lambda row: (
            {"required": 0, "high": 1, "medium": 2}[row["review_priority"]],
            row["patient_id"],
        )
    )
    exception_ids = {row["patient_id"] for row in exceptions}
    evidence_rows = [
        signal.row()
        for patient_id in sorted(exception_ids)
        for signal in _select_review_evidence(
            [
                item
                for item in evidence_by_patient[patient_id]
                if item.category
                in POSITIVE_CATEGORIES
                | {"normal_coronary_origin", "targeted_coronary_workup", "expected_coronary_origin"}
            ]
        )
    ]
    evidence_rows.sort(key=lambda row: (row["patient_id"], row["section_date"], row["section_id"], row["evidence_id"]))
    for row in exceptions:
        row.pop("_reasons", None)

    aggregate = {
        "ruleset_version": RULESET_VERSION,
        "method": extractor.method,
        "method_version": extractor.method_version,
        "patients_total": len(all_assessments),
        "automatic_judgments_all_patients": dict(Counter(row["automatic_aaoca_judgment"] for row in all_assessments)),
        "exception_patients": len(exceptions),
        "nonexception_patients": len(all_assessments) - len(exceptions),
        "exception_priorities": dict(Counter(row["review_priority"] for row in exceptions)),
        "exception_reason_counts": dict(Counter(reason for row in exceptions for reason in row["exception_reasons"])),
        "evidence_rows_for_exceptions": len(evidence_rows),
    }
    return exceptions, evidence_rows, aggregate


def write_exception_package(run_root: Path, output: Path) -> dict:
    """Write only exception patients plus their evidence to a local review dir."""
    run_root = Path(run_root).resolve()
    output = Path(output).resolve()
    if output == run_root or run_root.is_relative_to(output):
        raise ValueError("Review output must not contain or overwrite the source pipeline run")
    exceptions, evidence, aggregate = assess_patients(run_root)
    write_csv(output / "exception_cases.csv", exceptions, CASE_FIELDS)
    write_csv(output / "exception_evidence.csv", evidence, EVIDENCE_FIELDS)
    receipt = {
        **aggregate,
        "source_run": str(run_root),
        "source_run_metadata_sha256": sha256_file(run_root / "run_metadata.json"),
        "source_patient_manifest_sha256": sha256_file(run_root / "patient_manifest.csv"),
        "source_section_index_sha256": sha256_file(run_root / "section_index.csv"),
        "contains_direct_identifiers": True,
        "human_deliverable_scope": "exception_patients_only",
        "review_contract": {
            "review_status_values": ["not_reviewed", "in_review", "reviewed"],
            "final_aaoca_judgment_values": ["yes", "no", "uncertain"],
            "final_judgment_requires_reviewed_status": True,
        },
    }
    write_json(output / "run_metadata.json", receipt)
    write_text(
        output / "README.md",
        """# AAOCA 例外病例人工复核

本目录只包含规则识别出的例外病例，不包含普通高证据病例。
`exception_cases.csv` 每位患者一行；只修改 `review_status`、
`final_aaoca_judgment` 和 `reviewer_notes`。
`exception_evidence.csv` 保存证据、文书、section、页码和原文引用。

判定问题不是“最终是否确诊 AAOCA”，而是 AAOCA 或相应冠状动脉异常
是否曾真正进入考虑、怀疑、检查、讨论、鉴别或排除过程。即使后来排除，
只要发生过有意义的诊断尝试，最终仍应填写 `yes`。

允许值：`review_status` = `not_reviewed` / `in_review` / `reviewed`；
`final_aaoca_judgment` = `yes` / `no` / `uncertain`。
本目录含姓名和院内编号，只能在受限本地环境使用。
""",
    )
    return receipt


def validate_review_package(output: Path, require_complete: bool = False) -> dict:
    """Validate row linkage and editable human fields without source PDFs."""
    output = Path(output).resolve()
    cases = _read_csv(output / "exception_cases.csv")
    evidence = _read_csv(output / "exception_evidence.csv")
    metadata = json.loads((output / "run_metadata.json").read_text(encoding="utf-8"))
    errors: list[dict] = []
    ids = [row.get("patient_id", "") for row in cases]
    if not ids or len(ids) != len(set(ids)) or any(not value for value in ids):
        errors.append({"code": "invalid_or_duplicate_exception_patient_id"})
    evidence_patients = {row.get("patient_id", "") for row in evidence}
    if evidence_patients - set(ids):
        errors.append({"code": "evidence_patient_not_in_exception_cases"})
    if int(metadata.get("exception_patients", -1)) != len(cases):
        errors.append({"code": "metadata_exception_count_mismatch"})
    allowed_status = {"not_reviewed", "in_review", "reviewed"}
    allowed_final = {"", "yes", "no", "uncertain"}
    for row in cases:
        status = row.get("review_status", "")
        final = row.get("final_aaoca_judgment", "")
        if status not in allowed_status:
            errors.append({"code": "invalid_review_status", "patient_id": row.get("patient_id", "")})
        if final not in allowed_final:
            errors.append({"code": "invalid_final_judgment", "patient_id": row.get("patient_id", "")})
        if final and status != "reviewed":
            errors.append({"code": "final_judgment_without_reviewed_status", "patient_id": row.get("patient_id", "")})
        if require_complete and (status != "reviewed" or not final):
            errors.append({"code": "review_incomplete", "patient_id": row.get("patient_id", "")})
    return {
        "validation_status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "exception_patients": len(cases),
        "evidence_rows": len(evidence),
        "reviewed_patients": sum(row.get("review_status") == "reviewed" for row in cases),
        "complete_review_required": require_complete,
    }
