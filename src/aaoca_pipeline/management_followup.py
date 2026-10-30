"""Deterministic follow-up triage for unresolved AAOCA management records.

This module is deliberately downstream of the versioned management package.
It never rewrites source sections or the original management labels.  Instead,
it decomposes the unresolved cohort into three independent questions:

1. Is another complex cardiac disease documented strongly enough to make the
   AAOCA management question non-isolatable for the current study?
2. Did the treating team document an AAOCA surgical indication?
3. What AAOCA treatment outcome is actually documented?

That separation preserves clinically important paths such as "surgery was
recommended but the family deferred it" without turning them into clinician-
selected conservative management.  All labels retain exact source spans and
the rules can be replaced or extended with a JSON configuration file.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import csv
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from .io_utils import sha256_file, write_csv, write_json, write_text


SCHEMA_VERSION = "aaoca_management_followup_v1.0"
RULESET_VERSION = "aaoca_management_followup_rules_v1.0"

COMPLEX_STATUS_VALUES = {"confirmed", "suspected", "none"}
STUDY_DISPOSITION_VALUES = {
    "temporarily_excluded_complex_heart_disease",
    "needs_review_possible_complex_heart_disease",
    "retained_for_management_reclassification",
}
SURGERY_INDICATION_VALUES = {"yes", "no", "unclear"}
OUTCOME_VALUES = {
    "aaoca_surgery_completed",
    "conservative_followup",
    "no_aaoca_surgery_documented",
    "unknown",
}
DECISION_PATH_VALUES = {
    "combined_other_complex_heart_disease",
    "clinician_no_indication_conservative",
    "clinician_conservative_other",
    "surgery_indicated_not_done_family_declined",
    "surgery_indicated_not_done_family_deferred",
    "surgery_indicated_not_done_ama",
    "surgery_indicated_not_done_other",
    "surgery_indication_documented_outcome_unclear",
    "aaoca_not_treated_indication_unclear",
    "continued_evaluation_or_pending",
    "referred_no_outcome",
    "left_against_medical_advice_outcome_unclear",
    "other_cardiac_procedure_aaoca_handling_unresolved",
    "diagnostic_workup_terminal_decision_unresolved",
    "unclear",
}

SUMMARY_FIELDS = [
    "patient_id",
    "source_observed_management",
    "source_actual_aaoca_surgery",
    "source_overall_treatment_status",
    "source_other_cardiac_procedure_status",
    "source_aaoca_handling_during_other_procedure",
    "source_other_procedure_names",
    "source_complex_case_review_priority",
    "source_complex_case_review_reasons",
    "source_primary_evidence_id",
    "source_primary_document_id",
    "source_primary_section_id",
    "source_primary_page_start",
    "source_primary_page_end",
    "source_primary_text_path",
    "source_primary_text_reference",
    "complex_heart_disease_status",
    "complex_condition_codes",
    "complex_condition_labels",
    "complex_condition_evidence_ids",
    "study_disposition",
    "surgery_indication",
    "observed_aaoca_treatment_outcome",
    "decision_path",
    "followup_management",
    "classification_confidence",
    "classification_rule",
    "latest_decision_date",
    "primary_evidence_id",
    "primary_document_id",
    "primary_section_id",
    "primary_page_start",
    "primary_page_end",
    "primary_text_path",
    "primary_text_reference",
    "primary_evidence_text",
    "supporting_evidence_ids",
    "conflicting_evidence_ids",
    "n_followup_evidence_rows",
    "review_required",
    "review_reasons",
]

EVIDENCE_FIELDS = [
    "patient_id",
    "evidence_id",
    "domain",
    "assertion",
    "condition_code",
    "condition_label",
    "condition_status",
    "rule_id",
    "strength",
    "target_relation",
    "evidence_date",
    "document_id",
    "section_id",
    "section_type",
    "section_subtype",
    "section_title",
    "page_start",
    "page_end",
    "source_pdf",
    "text_path",
    "text_reference",
    "char_start",
    "char_end",
    "evidence_text",
    "flags",
]

REVIEW_FIELDS = [
    "patient_id",
    "decision_path",
    "issue_type",
    "severity",
    "evidence_ids",
    "detail",
]


DEFAULT_RULES = {
    "complex_conditions": [
        {
            "code": "hypertrophic_cardiomyopathy",
            "label": "肥厚型心肌病",
            "patterns": [r"肥厚(?:型|性)心肌病", r"梗阻性肥厚型心肌病", r"\bHOCM\b", r"\bHCM\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "long_qt_syndrome",
            "label": "长 QT 综合征",
            "patterns": [r"长\s*Q[-－—]?T\s*综合征", r"长\s*QT\s*综合征", r"\bLQTS\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "double_outlet_right_ventricle",
            "label": "右室双出口",
            "patterns": [r"右(?:心)?室双出[口又囗]", r"\bDORV\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "right_ventricular_outflow_obstruction",
            "label": "右室流出道狭窄或双腔右室",
            "patterns": [
                r"右(?:心)?室流出道(?:狭窄|梗阻)",
                r"右室双腔",
                r"双腔右室",
                r"\bDCRV\b",
            ],
            "temporary_exclusion": True,
        },
        {
            "code": "dilated_cardiomyopathy",
            "label": "扩张型心肌病",
            "patterns": [r"扩张(?:型|性)心肌病", r"\bDCM\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "arrhythmogenic_right_ventricular_cardiomyopathy",
            "label": "致心律失常性右室心肌病",
            "patterns": [r"致心律失常性?右(?:心)?室心肌病", r"\bARVC\b", r"\bARVD\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "restrictive_cardiomyopathy",
            "label": "限制型心肌病",
            "patterns": [r"限制型心肌病", r"\bRCM\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "great_artery_transposition",
            "label": "大动脉转位或纠正性大动脉转位",
            "patterns": [r"大动脉(?:转位|错位)", r"纠正性大动脉转位", r"\bD-?TGA\b", r"\bCCTGA\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "tetralogy_of_fallot",
            "label": "法洛四联症",
            "patterns": [r"法洛四联症", r"\bTOF\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "total_anomalous_pulmonary_venous_connection",
            "label": "完全性肺静脉异位引流",
            "patterns": [r"完全性肺静脉异位引流", r"\bTAPVC\b", r"\bTAPVR\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "single_ventricle_physiology",
            "label": "单心室生理或腔肺连接术后",
            "patterns": [r"单心室", r"Fontan", r"Glenn", r"格林手术", r"全腔肺连接"],
            "temporary_exclusion": True,
        },
        {
            "code": "pulmonary_atresia",
            "label": "肺动脉闭锁",
            "patterns": [r"肺动脉闭锁", r"\bPA/IVS\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "truncus_arteriosus",
            "label": "永存动脉干",
            "patterns": [r"永存动脉干", r"共同动脉干", r"\btruncus\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "hypoplastic_left_heart_syndrome",
            "label": "左心发育不良综合征",
            "patterns": [r"左心发育不良综合征", r"\bHLHS\b"],
            "temporary_exclusion": True,
        },
        {
            "code": "severe_pulmonary_hypertension",
            "label": "重度肺动脉高压或艾森曼格生理",
            "patterns": [r"重度肺动脉高压", r"艾森曼格", r"Eisenmenger"],
            "temporary_exclusion": True,
        },
        {
            "code": "critical_or_severe_aortic_stenosis",
            "label": "危重或重度主动脉瓣狭窄",
            "patterns": [
                r"(?:危重|重度|极重度)(?:型|的)?主动脉瓣狭窄",
                r"主动脉瓣(?:危重|重度|极重度)狭窄",
                r"(?:危重|重度|极重度)\s*AS\b",
                r"(?:critical|severe)\s+(?:valvar\s+)?aortic\s+stenosis",
            ],
            "temporary_exclusion": True,
        },
        {
            "code": "aortic_arch_obstruction",
            "label": "主动脉缩窄或主动脉弓中断",
            "patterns": [
                r"主动脉(?:弓)?缩窄",
                r"主动脉弓中断",
                r"\bCoA\b",
                r"\bIAA\b",
            ],
            "temporary_exclusion": True,
        },
    ],
    "phrases": {
        "no_surgery_indication": [
            r"(?:暂无|无|不具备|未发现|没有)(?:明确)?(?:AAOCA|冠(?:状动)?脉[^，。；;]{0,35})?(?:外科)?手术指[征证]",
            r"(?:暂无需|无需|不需)(?:外科)?(?:手术|干预|处理)",
        ],
        "active_conservative": [
            r"(?:建议|予以|予|继续)?保守(?:治疗|处理)",
            r"(?:继续|建议|嘱其?|予以)?(?:定期)?(?:心内科|心外科|胸外科)?(?:门诊)?随访观察",
            r"(?:继续|建议|嘱其?|予以)定期(?:心内科|心外科|胸外科)?(?:门诊)?随访",
            r"(?:继续|建议|嘱其?|予以)(?:后续|继续)?(?:心内科|心外科|胸外科)?(?:门诊)?随访",
            r"(?:3[.、．])?出院随访\s*(?:心内科|心血管内科|心内一|心内二)(?:门诊)?(?:定期)?(?:复诊|随访)?",
            r"(?:AAOCA|冠(?:状动)?脉[^。；;]{0,45}(?:异常起源|起源异常|起自|开[口又囗]于))[^。；;]{0,70}(?:未予(?:特殊)?处理|未处理|未干预)[^。；;]{0,70}(?:随访|复查|复诊)",
            r"(?:出院后)?定期复查(?:心电图|心脏彩超|运动平板|冠(?:状动)?脉)[^。；;]{0,80}",
            r"出院随访[^。；;]{0,35}(?:定期复查|每\s*\d+\s*[-–—至]\s*\d+\s*月)",
            r"(?:主诉|现病史)[:：\[]?[^。；;]{0,35}(?:AAOCA|冠(?:状动)?脉起源异常|冠脉起源异常)[^。；;]{0,120}(?:无胸痛|无晕厥|活动耐量正常|平素活动耐量正常)",
        ],
        "surgery_indication": [
            r"(?:具备|存在|有|符合)(?:AAOCA|冠(?:状动)?脉[^，。；;]{0,35})?(?:外科)?手术指[征证]",
            r"(?:建议|需|需要|应当|考虑)(?:尽快|择期)?[^。；;]{0,40}(?:冠(?:状动)?脉[^。；;]{0,20})?手术(?:治疗|干预)?",
        ],
        "aaoca_therapeutic_intent": [
            r"(?:拟定手术方式|拟行|计划行|建议行)[^。；;]{0,35}冠(?:状动)?脉[^。；;]{0,25}(?:开[口又囗]扩大|去顶|再植|移植|重建|松解|矫治|纠治|成形)",
            r"(?:冠(?:状动)?脉[^。；;]{0,18}(?:开[口又囗]扩大|去顶|再植|移植|重建|松解|矫治|纠治|成形)术)[^。；;]{0,25}(?:拟行|计划|建议|同意)",
        ],
        "family_declined": [
            r"(?:患儿)?(?:家属|家长)[^。；;]{0,60}(?:明确)?(?:拒绝|不同意|放弃)[^。；;]{0,25}手术",
            r"(?:拒绝|放弃)[^。；;]{0,25}手术[^。；;]{0,40}(?:要求|办理)?出院",
        ],
        "family_deferred": [
            r"(?:患儿)?(?:家属|家长)[^。；;]{0,70}(?:要求|决定|希望|考虑)?(?:暂缓|暂不|延期|择期|以后|寒假|暑假)[^。；;]{0,35}手术",
            r"手术[^。；;]{0,45}(?:延期|暂缓|暂不|寒假再做|日后再行)",
        ],
        "other_deferred": [
            r"(?:考虑|因)[^。；;]{0,35}(?:年龄|病情|风险|检查结果)[^。；;]{0,40}(?:暂缓|延期|暂不)[^。；;]{0,12}手术",
            r"(?:目前|现阶段|本次)?(?:暂缓|延期|暂不)[^。；;]{0,12}手术",
        ],
        "ama_or_requested_discharge": [
            r"(?:患儿)?家属[^。；;]{0,45}(?:要求|坚持|决定)(?:办理)?(?:自动)?出院",
            r"自动出院",
        ],
        "explicit_not_performed": [
            r"(?:本次|此次|术中)?(?:未行|未予|未能行|未实施|未处理|不予处理)[^。；;]{0,40}(?:冠(?:状动)?脉|AAOCA|手术|成形|纠治|矫治)",
            r"(?:冠(?:状动)?脉|AAOCA)[^。；;]{0,50}(?:未行|未予|未实施|未处理|不予处理)",
        ],
        "continued_evaluation": [
            r"(?:待|需|拟)[^。；;]{0,30}(?:进一步)?(?:检查|评估|讨论|会诊|决定|制定)[^。；;]{0,25}(?:方案|计划|手术指征)?",
            r"完善[^。；;]{0,35}(?:检查|评估)[^。；;]{0,45}(?:再|后|进一步)(?:决定|评估|讨论|制定)",
            r"(?:建议|拟|需|待)[^。；;]{0,45}(?:心导管|冠(?:状动)?脉造影|心脏MRI|运动心电图|负荷试验)[^。；;]{0,20}(?:检查|评估)?",
            r"(?:MDT|多学科)[^。；;]{0,35}(?:讨论|评估)",
            r"出院[^。；;]{0,35}(?:预约|完善|行)[^。；;]{0,25}(?:心脏MRI|运动平板|冠(?:状动)?脉造影|心脏CT)[^。；;]{0,20}(?:检查|试验|评估)?",
        ],
        "conditional_surgery": [
            r"(?:如|若|待)[^。；;]{0,35}(?:缺血|阳性|异常|证实)[^。；;]{0,35}(?:建议|考虑|再行)[^。；;]{0,25}手术",
        ],
        "referred_without_outcome": [
            r"(?:建议|转|请)[^。；;]{0,18}(?:心胸外科|胸外科|心外科)(?:门诊)?(?:就诊|随访|会诊)",
            r"(?:心胸外科|胸外科|心外科)(?:门诊)?(?:就诊|随访)[^。；;]{0,35}(?:评估|决定|手术)?",
            r"出院随访[^。；;]{0,16}(?:心胸外科|胸外科|心外科)",
            r"出院后(?:就诊|随访)于?(?:心胸外科|胸外科|心外科)",
        ],
    },
    "section_priorities": {
        "procedure:surgery_record": 90,
        "discharge:": 80,
        "progress:case_discussion": 75,
        "consultation:": 70,
        "progress:round": 65,
        "progress:first_round": 60,
        "procedure:preoperative_discussion": 55,
        "progress:initial_progress": 50,
        "admission:": 45,
        "administrative:condition_communication": 30,
        "administrative:treatment_procedure_consent": 20,
        "nonclinical:web_navigation": 15,
    },
}


AAOCA_ANCHOR_RE = re.compile(
    r"AAOCA|AORCA|ALCA(?:PA)?|冠(?:状动)?脉缺血|冠(?:状动)?脉.{0,35}(?:异常起源|起源异常|异位起源|开[口又囗]异常|壁内走行)|"
    r"(?:左|右)冠(?:状动脉)?起源异常|"
    r"(?:左|右)冠(?:状动脉)?.{0,25}(?:起自|起源(?:于)?|发自|开[口又囗](?:于)?).{0,25}(?:冠(?:状)?窦|主动脉|肺动脉)",
    re.I | re.S,
)

DIAGNOSTIC_PROCEDURE_RE = re.compile(
    r"冠(?:状动)?脉造影|升主动脉造影|左右心联合造影|心导管检查|右心导管|左心导管|血管造影|电生理检查",
    re.I,
)

AAOCA_THERAPEUTIC_RE = re.compile(
    r"冠(?:状动)?脉[^。；;]{0,20}(?:去顶|开[口又囗]成形|扩大|再植|移植|重建|松解|修补|搭桥|旁路|纠治|矫治)",
    re.I,
)

COMPETING_LESION_RE = re.compile(
    r"房间隔缺损|室间隔缺损|房室间隔缺损|动脉导管未闭|主动脉缩窄|肺动脉瓣狭窄|"
    r"右室流出道|右室双腔|右室双出口|肥厚(?:型|性)心肌病|大动脉转位|法洛四联症|"
    r"肺动脉闭锁|单心室|瓣膜(?:狭窄|关闭不全)|心肌病",
    re.I,
)

POSTOPERATIVE_LESION_RE = re.compile(
    r"(?:房间隔缺损|室间隔缺损|动脉导管未闭)[^，,。；;\n]{0,18}(?:修补|封堵|结扎)?术后",
    re.I,
)

OTHER_DECISION_TARGET_RE = re.compile(
    r"(?:纵[隔膈])?(?:占位|肿物)|支气管源性囊肿|肿瘤|活检|射频消融|"
    r"起搏器|除颤器|\bICD\b|\bCRT\b|神经外科|神经内科|"
    r"动态心电图|心内电生理|室性心动过速|室上性心动过速|"
    r"房间隔缺损|室间隔缺损|肺动脉瓣狭窄|肺静脉异位引流|动脉导管未闭|瓣膜(?:狭窄|关闭不全)",
    re.I,
)

NON_AAOCA_FOLLOWUP_TARGET_RE = re.compile(
    r"出院随访[^。；;\n]{0,80}(?:呼吸|神经|内分泌|遗传|代谢|肾脏|心理|精神|"
    r"血管|风湿|免疫|感染|消化|血液|肿瘤|骨科|泌尿|康复)(?:科|门诊)?",
    re.I,
)

IMAGING_ONLY_FOLLOWUP_RE = re.compile(
    r"(?:MRI|MR成像|CT|ECHO|彩超|超声|影像)[^。；;\n]{0,100}(?:建议)?随访",
    re.I,
)

TEMPLATE_INSTRUCTION_RE = re.compile(
    r"需要描述|要写明|最好写清楚|要求填写|请输入|预判检查结果|模板",
    re.I,
)

STRUCTURED_DIAGNOSIS_RE = re.compile(
    r"(?:出院|入院|目前|初步|主要|最终|会诊)诊断\s*[:：]\s*"
    r"(?P<diagnoses>.{1,260}?)(?=\n|【|治疗结果|出院带药|诊疗经过|尊敬|$)",
    re.I | re.S,
)

DIAGNOSIS_MARKER_RE = re.compile(
    r"出院诊断|入院诊断|门急诊入院(?:诊断|臆断)|初步诊断|目前诊断|术前诊断|术后诊断|"
    r"(?<!鉴别)(?<!排除)(?:明确|主要|最终)?诊断(?:为|[:：])|既往诊断为|故诊断",
    re.I,
)

DIFFERENTIAL_MARKER_RE = re.compile(r"鉴别诊断|可排除诊断|排除诊断", re.I)
RULED_OUT_RE = re.compile(
    r"可排除(?:诊断)?|予以排除|排除(?:诊断)?|不支持|不考虑|未见|否认|排外",
    re.I,
)
SUSPECTED_RE = re.compile(r"待查|待排|疑似|可能|考虑|不能排除|不除外|[?？]", re.I)


@dataclass(frozen=True)
class CompiledCondition:
    code: str
    label: str
    patterns: tuple[re.Pattern[str], ...]
    temporary_exclusion: bool


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


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_rules(path: Path | None = None) -> dict:
    """Load the default rules and apply an optional JSON override."""

    rules = deepcopy(DEFAULT_RULES)
    if path is not None:
        override = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(override, dict):
            raise ValueError("Rules override must be a JSON object")
        rules = _deep_merge(rules, override)
    if not rules.get("complex_conditions"):
        raise ValueError("At least one complex-condition rule is required")
    required_phrase_groups = set(DEFAULT_RULES["phrases"])
    missing = required_phrase_groups - set(rules.get("phrases", {}))
    if missing:
        raise ValueError(f"Rules are missing phrase groups: {sorted(missing)}")
    return rules


def _compile_conditions(rules: dict) -> list[CompiledCondition]:
    compiled: list[CompiledCondition] = []
    seen: set[str] = set()
    for item in rules["complex_conditions"]:
        code = str(item.get("code", "")).strip()
        label = str(item.get("label", "")).strip()
        patterns = item.get("patterns") or []
        if not code or code in seen or not label or not patterns:
            raise ValueError(f"Invalid or duplicate complex-condition rule: {item}")
        seen.add(code)
        compiled.append(
            CompiledCondition(
                code=code,
                label=label,
                patterns=tuple(re.compile(pattern, re.I | re.S) for pattern in patterns),
                temporary_exclusion=bool(item.get("temporary_exclusion", True)),
            )
        )
    return compiled


def _compile_phrases(rules: dict) -> dict[str, tuple[re.Pattern[str], ...]]:
    return {
        name: tuple(re.compile(pattern, re.I | re.S) for pattern in patterns)
        for name, patterns in rules["phrases"].items()
    }


def load_sections(run_root: Path, patient_ids: set[str]) -> list[dict]:
    sections_dir = run_root / "sections"
    if not sections_dir.is_dir():
        raise ValueError("Completed pipeline snapshot is missing sections/")
    result: list[dict] = []
    seen: set[str] = set()
    for path in sorted(sections_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        patient_id = payload.get("patient_id", "")
        if patient_id not in patient_ids:
            continue
        for section in payload.get("sections", []):
            section_id = section.get("section_id", "")
            if not section_id or section_id in seen:
                raise ValueError(f"Missing or duplicate section_id: {section_id}")
            seen.add(section_id)
            result.append(section)
    return result


def _sentence_bounds(text: str, start: int, end: int, radius: int = 220) -> tuple[int, int]:
    left = max(text.rfind(mark, max(0, start - radius), start) for mark in "。；;\n") + 1
    stops = [text.find(mark, end, min(len(text), end + radius)) for mark in "。；;\n"]
    stops = [stop for stop in stops if stop >= 0]
    right = min(stops) + 1 if stops else min(len(text), end + radius)
    if right <= left:
        return max(0, start - radius), min(len(text), end + radius)
    return left, right


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _compact_text_with_map(text: str) -> tuple[str, list[int]]:
    """Remove OCR/layout whitespace while retaining raw character offsets."""

    characters: list[str] = []
    raw_positions: list[int] = []
    for index, character in enumerate(text):
        if character.isspace():
            continue
        characters.append(character)
        raw_positions.append(index)
    return "".join(characters), raw_positions


def _raw_span(raw_positions: list[int], start: int, end: int) -> tuple[int, int]:
    if not raw_positions or start >= len(raw_positions):
        return 0, 0
    raw_start = raw_positions[max(0, start)]
    raw_end_index = min(len(raw_positions) - 1, max(start, end - 1))
    return raw_start, raw_positions[raw_end_index] + 1


def _evidence_date(section: dict) -> str:
    for key in ("section_date", "document_date"):
        value = str(section.get(key, "") or "")[:10]
        try:
            date.fromisoformat(value)
        except ValueError:
            continue
        return value
    return ""


def _section_priority(section: dict, rules: dict) -> int:
    section_type = str(section.get("section_type", ""))
    subtype = str(section.get("section_subtype", ""))
    priorities = rules.get("section_priorities", {})
    return int(
        priorities.get(
            f"{section_type}:{subtype}",
            priorities.get(f"{section_type}:", 10),
        )
    )


def _make_evidence(
    section: dict,
    *,
    domain: str,
    assertion: str,
    rule_id: str,
    strength: str,
    target_relation: str,
    start: int,
    end: int,
    condition_code: str = "",
    condition_label: str = "",
    condition_status: str = "",
    flags: Iterable[str] = (),
) -> dict:
    text = section.get("text", "") or ""
    start, end = _trim_span(text, max(0, start), min(len(text), end))
    evidence_id = _stable_id(
        "amf",
        section.get("patient_id", ""),
        section.get("section_id", ""),
        domain,
        assertion,
        condition_code,
        start,
        end,
    )
    return {
        "patient_id": section.get("patient_id", ""),
        "evidence_id": evidence_id,
        "domain": domain,
        "assertion": assertion,
        "condition_code": condition_code,
        "condition_label": condition_label,
        "condition_status": condition_status,
        "rule_id": rule_id,
        "strength": strength,
        "target_relation": target_relation,
        "evidence_date": _evidence_date(section),
        "document_id": section.get("document_id", ""),
        "section_id": section.get("section_id", ""),
        "section_type": section.get("section_type", ""),
        "section_subtype": section.get("section_subtype", ""),
        "section_title": section.get("section_title", ""),
        "page_start": section.get("page_start", ""),
        "page_end": section.get("page_end", ""),
        "source_pdf": section.get("source_pdf", ""),
        "text_path": section.get("text_path", ""),
        "text_reference": section.get("text_reference", ""),
        "char_start": start,
        "char_end": end,
        "evidence_text": text[start:end],
        "flags": list(dict.fromkeys(str(flag) for flag in flags if flag)),
        "_priority": 0,
    }


def _nearby(text: str, start: int, end: int, radius: int = 300) -> tuple[int, int, str]:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return left, right, text[left:right]


def _condition_context_status(section: dict, start: int, end: int) -> tuple[str, str, list[str]]:
    text = section.get("text", "") or ""
    sent_start, sent_end = _sentence_bounds(text, start, end, radius=260)
    sentence = text[sent_start:sent_end]
    local_start, local_end, local = _nearby(text, start, end, radius=90)
    relative_start = start - local_start
    relative_end = end - local_start
    before = local[max(0, relative_start - 55) : relative_start]
    after = local[relative_end : min(len(local), relative_end + 55)]
    flags: list[str] = []

    prefix = text[max(0, start - 260) : start]
    last_diagnosis = max((match.start() for match in DIAGNOSIS_MARKER_RE.finditer(prefix)), default=-1)
    last_differential = max((match.start() for match in DIFFERENTIAL_MARKER_RE.finditer(prefix)), default=-1)
    if re.search(r"(?:未见|未提示|无|排除|否认|不支持)\s*$", before[-18:], re.I) or RULED_OUT_RE.search(sentence):
        flags.append("negated_or_differential_context")
        return "ruled_out", "low", flags
    if last_differential > last_diagnosis:
        flags.append("differential_diagnosis_context")
        return "mention", "low", flags
    if SUSPECTED_RE.search(before) or SUSPECTED_RE.search(after):
        flags.append("suspected_or_pending_diagnosis")
        return "suspected", "medium", flags

    section_type = section.get("section_type", "")
    subtype = section.get("section_subtype", "")
    title = section.get("section_title", "") or ""
    diagnosis_context = bool(DIAGNOSIS_MARKER_RE.search(prefix[-180:] + sentence[:180]))
    if section_type == "discharge" and start < max(800, text.find("【入院情况】") if "【入院情况】" in text else 800):
        diagnosis_context = True
    if section_type == "nonclinical" and "出院诊断" in prefix[-180:] + sentence:
        diagnosis_context = True
    if section_type == "procedure" and re.search(r"术[前后]诊断", prefix[-140:] + sentence):
        diagnosis_context = True
    if diagnosis_context and section_type in {"admission", "progress", "discharge", "consultation", "procedure", "nonclinical"}:
        strength = "high" if section_type == "discharge" or "出院诊断" in prefix[-180:] + sentence else "medium"
        return "confirmed", strength, flags
    if subtype in {"initial_progress", "first_round", "case_discussion"} and re.search(r"诊断(?:明确|为|[:：])", prefix[-120:] + sentence):
        return "confirmed", "medium", flags
    if re.search(r"(?:既往|曾|外院)[^。；;]{0,30}诊断为?", prefix[-120:] + sentence):
        flags.append("historical_diagnosis")
        return "confirmed", "medium", flags
    if "知情同意" in title or subtype == "treatment_procedure_consent":
        flags.append("consent_or_template_context")
    return "mention", "low", flags


def extract_complex_condition_evidence(sections: Iterable[dict], rules: dict) -> list[dict]:
    conditions = _compile_conditions(rules)
    evidence: list[dict] = []
    seen: set[tuple] = set()
    for section in sections:
        text = section.get("text", "") or ""
        compact_text, raw_positions = _compact_text_with_map(text)
        for condition in conditions:
            for pattern in condition.patterns:
                for match in pattern.finditer(compact_text):
                    raw_start, raw_end = _raw_span(raw_positions, match.start(), match.end())
                    key = (section.get("section_id", ""), condition.code, raw_start, raw_end)
                    if key in seen:
                        continue
                    seen.add(key)
                    status, strength, flags = _condition_context_status(section, raw_start, raw_end)
                    start, end = _sentence_bounds(text, raw_start, raw_end, radius=240)
                    row = _make_evidence(
                        section,
                        domain="complex_condition",
                        assertion="complex_condition_mention",
                        rule_id=f"complex_{condition.code}",
                        strength=strength,
                        target_relation="other_complex_cardiac_disease",
                        start=start,
                        end=end,
                        condition_code=condition.code,
                        condition_label=condition.label,
                        condition_status=status,
                        flags=flags,
                    )
                    row["_temporary_exclusion"] = condition.temporary_exclusion
                    row["_priority"] = _section_priority(section, rules)
                    evidence.append(row)
    return evidence


def _has_aaoca_anchor(text: str, start: int, end: int, radius: int = 360) -> bool:
    _, _, local = _nearby(text, start, end, radius=radius)
    return bool(AAOCA_ANCHOR_RE.search(local))


def _section_has_aaoca_only_diagnosis(section: dict) -> bool:
    """Return true when a terminal decision section diagnoses AAOCA without a competing lesion.

    This is intentionally narrower than a generic nearby-keyword bridge.  It
    only links decisions in later, clinician-authored synthesis sections and
    requires a structured diagnosis field in the same section.
    """

    section_type = str(section.get("section_type", ""))
    section_subtype = str(section.get("section_subtype", ""))
    if section_type not in {"discharge", "consultation", "progress"}:
        return False
    if section_type == "progress" and section_subtype not in {"case_discussion", "round", "first_round"}:
        return False
    text = section.get("text", "") or ""
    for match in STRUCTURED_DIAGNOSIS_RE.finditer(text):
        diagnoses = POSTOPERATIVE_LESION_RE.sub("", match.group("diagnoses"))
        if AAOCA_ANCHOR_RE.search(diagnoses) and not COMPETING_LESION_RE.search(diagnoses):
            return True
    return False


def _target_relation(
    section: dict,
    start: int,
    end: int,
    *,
    diagnostic_procedure_is_target: bool = False,
) -> tuple[str, list[str]]:
    text = section.get("text", "") or ""
    sent_start, sent_end = _sentence_bounds(text, start, end, radius=320)
    sentence = text[sent_start:sent_end]
    sentence_has_anchor = bool(AAOCA_ANCHOR_RE.search(sentence))
    nearby_has_anchor = _has_aaoca_anchor(text, start, end)
    flags: list[str] = []
    if AAOCA_THERAPEUTIC_RE.search(sentence):
        return "aaoca", flags
    if (
        diagnostic_procedure_is_target
        and not AAOCA_THERAPEUTIC_RE.search(text)
        and (
            DIAGNOSTIC_PROCEDURE_RE.search(sentence)
            or (
                section.get("section_subtype") == "preoperative_discussion"
                and DIAGNOSTIC_PROCEDURE_RE.search(text)
            )
        )
    ):
        flags.append("diagnostic_procedure_indication_not_therapeutic_indication")
        return "diagnostic_procedure", flags
    if sentence_has_anchor:
        if COMPETING_LESION_RE.search(sentence) and not re.search(r"(?:AAOCA|冠(?:状动)?脉)[^。；;]{0,35}手术", sentence, re.I):
            flags.append("surgical_target_may_be_competing_lesion")
            return "ambiguous_target", flags
        return "aaoca", flags
    if OTHER_DECISION_TARGET_RE.search(sentence):
        flags.append("decision_sentence_names_non_aaoca_target")
        return "other_or_ambiguous", flags
    if _section_has_aaoca_only_diagnosis(section):
        flags.append("aaoca_linked_by_structured_section_diagnosis")
        return "aaoca", flags
    if nearby_has_anchor:
        flags.append("aaoca_anchor_not_in_same_decision_sentence")
        return "aaoca_nearby_only", flags
    if COMPETING_LESION_RE.search(sentence):
        flags.append("surgical_target_is_other_or_ambiguous")
        return "other_or_ambiguous", flags
    return "unlinked", flags


def extract_management_followup_evidence(sections: Iterable[dict], rules: dict) -> list[dict]:
    phrases = _compile_phrases(rules)
    evidence: list[dict] = []
    seen: set[tuple] = set()
    assertion_map = {
        "no_surgery_indication": "no_surgery_indication",
        "active_conservative": "active_conservative",
        "surgery_indication": "surgery_indication",
        "aaoca_therapeutic_intent": "surgery_indication",
        "family_declined": "family_declined",
        "family_deferred": "family_deferred",
        "other_deferred": "other_deferred",
        "ama_or_requested_discharge": "ama_or_requested_discharge",
        "explicit_not_performed": "explicit_not_performed",
        "continued_evaluation": "continued_evaluation",
        "conditional_surgery": "continued_evaluation",
        "referred_without_outcome": "referred_without_outcome",
    }
    aaoca_target_required = {
        "no_surgery_indication",
        "active_conservative",
        "explicit_not_performed",
        "other_deferred",
        "continued_evaluation",
        "referred_without_outcome",
    }
    for section in sections:
        text = section.get("text", "") or ""
        if not text:
            continue
        compact_text, raw_positions = _compact_text_with_map(text)
        for group, patterns in phrases.items():
            for pattern in patterns:
                for match in pattern.finditer(compact_text):
                    raw_start, raw_end = _raw_span(raw_positions, match.start(), match.end())
                    key = (section.get("section_id", ""), group, raw_start, raw_end)
                    if key in seen:
                        continue
                    seen.add(key)
                    target, flags = _target_relation(
                        section,
                        raw_start,
                        raw_end,
                        diagnostic_procedure_is_target=(group in {"surgery_indication", "aaoca_therapeutic_intent"}),
                    )
                    sent_start, sent_end = _sentence_bounds(text, raw_start, raw_end, radius=320)
                    decision_sentence = text[sent_start:sent_end]
                    if group == "active_conservative" and target == "aaoca_nearby_only":
                        _, _, adjacent = _nearby(text, raw_start, raw_end, radius=180)
                        if re.search(r"无明显冠(?:状动)?脉缺血证据", adjacent, re.I):
                            target = "aaoca"
                            flags.append("aaoca_linked_by_adjacent_no_ischemia_assessment")
                    if TEMPLATE_INSTRUCTION_RE.search(decision_sentence):
                        continue
                    if group in aaoca_target_required and target != "aaoca":
                        continue
                    if group == "conditional_surgery" and target not in {"aaoca", "aaoca_nearby_only"}:
                        continue
                    if group == "aaoca_therapeutic_intent" and target != "aaoca":
                        continue
                    if group == "no_surgery_indication":
                        question_context = text[max(0, raw_start - 24) : min(len(text), raw_end + 12)]
                        if re.search(r"评估有无|明确有无|判断有无|是否有|有无外科|进一步评估", question_context, re.I):
                            continue
                        if "aaoca_linked_by_structured_section_diagnosis" in flags and not re.search(
                            r"手术指[征证]|(?:外科)?手术", compact_text[match.start() : match.end()], re.I
                        ):
                            continue
                    if group == "surgery_indication" and re.search(
                        r"评估(?:有无|是否|其)?手术指[征证]|明确有无手术指[征证]|有否手术指[征证]|"
                        r"根据[^。；;]{0,20}(?:检查|评估)结果[^。；;]{0,20}(?:再)?(?:评估|决定)手术",
                        decision_sentence,
                        re.I,
                    ):
                        continue
                    if (
                        group == "surgery_indication"
                        and section.get("section_subtype") == "preoperative_discussion"
                        and not AAOCA_THERAPEUTIC_RE.search(text)
                    ):
                        continue
                    if group == "active_conservative" and section.get("section_type") == "admission":
                        continue
                    if group == "active_conservative":
                        # A generic discharge template may list several unrelated
                        # specialties, and radiology reports commonly end with
                        # "结合 ECHO，建议随访".  Neither is an affirmative AAOCA
                        # management decision unless the same sentence identifies
                        # the coronary anomaly itself.
                        direct_aaoca = bool(AAOCA_ANCHOR_RE.search(decision_sentence))
                        if NON_AAOCA_FOLLOWUP_TARGET_RE.search(decision_sentence):
                            continue
                        if IMAGING_ONLY_FOLLOWUP_RE.search(decision_sentence) and not direct_aaoca:
                            continue
                    if group == "continued_evaluation" and (
                        section.get("section_type") in {"admission", "administrative"}
                        or section.get("section_subtype") in {"treatment_procedure_consent", "preoperative_discussion"}
                    ):
                        continue
                    assertion = assertion_map[group]
                    strength = "medium"
                    if group == "active_conservative" and (
                        re.search(r"无明显冠(?:状动)?脉缺血证据", decision_sentence, re.I)
                        or "aaoca_linked_by_adjacent_no_ischemia_assessment" in flags
                        or (
                            section.get("section_type") == "outpatient"
                            and AAOCA_ANCHOR_RE.search(decision_sentence)
                            and re.search(r"无胸痛|无晕厥|活动耐量正常", decision_sentence, re.I)
                        )
                        or (
                            AAOCA_ANCHOR_RE.search(decision_sentence)
                            and re.search(r"(?:建议|定期|继续|嘱)[^。；;]{0,30}(?:随访|复查|复诊)", decision_sentence, re.I)
                        )
                        or re.search(
                            r"定期复查(?:心电图|心脏彩超|运动平板|冠(?:状动)?脉)",
                            decision_sentence,
                            re.I,
                        )
                    ):
                        strength = "high"
                    if group == "aaoca_therapeutic_intent":
                        strength = "high"
                    if group == "surgery_indication" and target == "diagnostic_procedure":
                        assertion = "diagnostic_procedure_indication"
                        strength = "low"
                    elif group == "surgery_indication" and target != "aaoca":
                        if target not in {"aaoca_nearby_only", "ambiguous_target"}:
                            continue
                        assertion = "surgery_indication_ambiguous_target"
                        strength = "low"
                    elif group in {
                        "no_surgery_indication",
                        "family_declined",
                        "family_deferred",
                        "other_deferred",
                        "explicit_not_performed",
                    }:
                        strength = "high" if target in {"aaoca", "unlinked"} else "medium"
                    elif group == "ama_or_requested_discharge":
                        target = "encounter_disposition"
                    elif group in {"continued_evaluation", "referred_without_outcome"} and target != "aaoca":
                        continue

                    start, end = _sentence_bounds(text, raw_start, raw_end, radius=260)
                    row = _make_evidence(
                        section,
                        domain="management_decision",
                        assertion=assertion,
                        rule_id=f"followup_{group}",
                        strength=strength,
                        target_relation=target,
                        start=start,
                        end=end,
                        flags=flags,
                    )
                    row["_priority"] = _section_priority(section, rules)
                    evidence.append(row)
    return evidence


def extract_followup_evidence(sections: Iterable[dict], rules: dict) -> list[dict]:
    section_list = list(sections)
    extracted = [
        *extract_complex_condition_evidence(section_list, rules),
        *extract_management_followup_evidence(section_list, rules),
    ]
    # Different aliases or phrase variants can resolve to the same enclosing
    # source sentence.  The evidence ID is span-bound, so retain one row and
    # merge its flags rather than multiplying identical clinical evidence.
    strength_rank = {"low": 1, "medium": 2, "high": 3}
    by_id: dict[str, dict] = {}
    for row in extracted:
        existing = by_id.get(row["evidence_id"])
        if existing is None:
            by_id[row["evidence_id"]] = row
            continue
        combined_flags = _serialize_list([*existing.get("flags", []), *row.get("flags", [])])
        if strength_rank.get(row.get("strength", ""), 0) > strength_rank.get(existing.get("strength", ""), 0):
            row["flags"] = combined_flags
            by_id[row["evidence_id"]] = row
        else:
            existing["flags"] = combined_flags
    rows = list(by_id.values())
    rows.sort(key=lambda row: (row["patient_id"], row["document_id"], row["section_id"], int(row["char_start"]), row["evidence_id"]))
    return rows


def _event_key(row: dict) -> tuple:
    date_value = row.get("evidence_date", "") or "0000-00-00"
    try:
        page_value = int(row.get("page_start", 0) or 0)
    except (TypeError, ValueError):
        page_value = 0
    strength_rank = {"low": 1, "medium": 2, "high": 3}
    return (
        date_value,
        strength_rank.get(row.get("strength", ""), 0),
        int(row.get("_priority", 0)),
        row.get("document_id", ""),
        page_value,
        int(row.get("char_start", 0)),
    )


def _at_or_after(later: dict, earlier: dict) -> bool:
    later_date = later.get("evidence_date", "")
    earlier_date = earlier.get("evidence_date", "")
    if later_date and earlier_date:
        return later_date >= earlier_date
    if later.get("document_id") == earlier.get("document_id"):
        try:
            return (int(later.get("page_start", 0) or 0), int(later.get("char_start", 0))) >= (
                int(earlier.get("page_start", 0) or 0),
                int(earlier.get("char_start", 0)),
            )
        except (TypeError, ValueError):
            return False
    return False


def _condition_summary(rows: list[dict]) -> tuple[str, list[dict], list[dict]]:
    by_code: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["domain"] == "complex_condition":
            by_code[row["condition_code"]].append(row)
    confirmed: list[dict] = []
    suspected: list[dict] = []
    for condition_rows in by_code.values():
        confirmed_rows = [row for row in condition_rows if row["condition_status"] == "confirmed"]
        suspected_rows = [row for row in condition_rows if row["condition_status"] == "suspected"]
        if confirmed_rows:
            confirmed.append(max(confirmed_rows, key=_event_key))
        elif suspected_rows:
            suspected.append(max(suspected_rows, key=_event_key))
    if confirmed:
        return "confirmed", sorted(confirmed, key=_event_key), sorted(suspected, key=_event_key)
    if suspected:
        return "suspected", [], sorted(suspected, key=_event_key)
    return "none", [], []


def _latest(rows: list[dict]) -> dict | None:
    return max(rows, key=_event_key) if rows else None


def _after_any(rows: list[dict], anchors: list[dict]) -> list[dict]:
    if not anchors:
        return rows
    return [row for row in rows if any(_at_or_after(row, anchor) for anchor in anchors)]


def _serialize_list(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _classify_patient(source: dict, evidence: list[dict]) -> tuple[dict, list[dict]]:
    complex_status, confirmed_conditions, suspected_conditions = _condition_summary(evidence)
    decisions = [row for row in evidence if row["domain"] == "management_decision"]
    by_assertion: dict[str, list[dict]] = defaultdict(list)
    for row in decisions:
        by_assertion[row["assertion"]].append(row)

    no_indication = sorted(by_assertion["no_surgery_indication"], key=_event_key)
    conservative = sorted(by_assertion["active_conservative"], key=_event_key)
    indications = sorted(by_assertion["surgery_indication"], key=_event_key)
    ambiguous_indications = sorted(by_assertion["surgery_indication_ambiguous_target"], key=_event_key)
    declines = sorted(by_assertion["family_declined"], key=_event_key)
    deferrals = sorted(by_assertion["family_deferred"], key=_event_key)
    other_deferrals = sorted(by_assertion["other_deferred"], key=_event_key)
    amas = sorted(by_assertion["ama_or_requested_discharge"], key=_event_key)
    actual_amas = [
        row
        for row in amas
        if row.get("evidence_date")
        and row.get("section_type") in {"progress", "discharge", "consultation"}
    ]
    explicit_not_done = sorted(by_assertion["explicit_not_performed"], key=_event_key)
    pending = sorted(by_assertion["continued_evaluation"], key=_event_key)
    referred = sorted(by_assertion["referred_without_outcome"], key=_event_key)

    review_reasons: list[str] = []
    conflict_rows: list[dict] = []
    qc: list[dict] = []
    source_complex_review_reasons = _json_list(source.get("complex_case_review_reasons"))
    if source.get("complex_case_review_priority") == "high":
        review_reasons.append("source_complex_procedure_context_requires_review")

    if complex_status == "confirmed":
        study_disposition = "temporarily_excluded_complex_heart_disease"
    elif complex_status == "suspected":
        study_disposition = "needs_review_possible_complex_heart_disease"
        review_reasons.append("possible_complex_heart_disease_not_confirmed")
    else:
        study_disposition = "retained_for_management_reclassification"

    indication = "unclear"
    latest_intent = _latest(indications)
    latest_no_indication = _latest(no_indication)
    if latest_intent and latest_no_indication:
        if _at_or_after(latest_no_indication, latest_intent):
            indication = "no"
            conflict_rows.extend(indications)
        elif _at_or_after(latest_intent, latest_no_indication):
            indication = "yes"
            conflict_rows.extend(no_indication)
        else:
            indication = "unclear"
            conflict_rows.extend([*indications, *no_indication])
            review_reasons.append("conflicting_indication_evidence_chronology_unresolved")
    elif latest_intent:
        indication = "yes"
    elif latest_no_indication:
        indication = "no"
    if ambiguous_indications:
        review_reasons.append("surgical_indication_target_ambiguous")

    path = "unclear"
    outcome = "unknown"
    followup_management = "pending_or_unresolved"
    confidence = "low"
    classification_rule = "insufficient_terminal_management_evidence"
    primary: dict | None = None

    if complex_status == "confirmed":
        path = "combined_other_complex_heart_disease"
        followup_management = "excluded_complex_heart_disease"
        confidence = "high" if any(row["strength"] == "high" for row in confirmed_conditions) else "medium"
        classification_rule = "confirmed_complex_cardiac_disease_temporary_exclusion"
        primary = _latest(confirmed_conditions)
    elif source.get("actual_aaoca_surgery") == "yes":
        outcome = "aaoca_surgery_completed"
        followup_management = "surgery"
        confidence = "high"
        classification_rule = "source_completed_aaoca_surgery"
    elif indication == "no" and latest_no_indication:
        path = "clinician_no_indication_conservative"
        outcome = "conservative_followup"
        followup_management = "conservative"
        confidence = "high" if latest_no_indication["strength"] == "high" else "medium"
        classification_rule = "later_explicit_no_surgical_indication"
        primary = latest_no_indication
    elif indication == "yes" and latest_intent:
        reason_groups = [
            ("surgery_indicated_not_done_family_declined", _after_any(declines, indications)),
            ("surgery_indicated_not_done_family_deferred", _after_any(deferrals, indications)),
            ("surgery_indicated_not_done_ama", _after_any(amas, indications)),
            ("surgery_indicated_not_done_other", _after_any(explicit_not_done, indications)),
            ("surgery_indicated_not_done_other", _after_any(other_deferrals, indications)),
        ]
        reason_candidates = [(name, _latest(rows)) for name, rows in reason_groups if rows]
        if reason_candidates:
            path, reason_primary = max(reason_candidates, key=lambda item: _event_key(item[1]))
            outcome = "no_aaoca_surgery_documented"
            followup_management = "intended_surgery_not_completed"
            confidence = "high" if reason_primary["strength"] == "high" else "medium"
            classification_rule = path
            primary = reason_primary
        elif _after_any(pending, indications):
            path = "continued_evaluation_or_pending"
            followup_management = "intended_surgery_not_completed"
            confidence = "medium"
            classification_rule = "surgical_indication_with_later_pending_evaluation"
            primary = _latest(_after_any(pending, indications))
            review_reasons.append("surgical_indication_present_but_terminal_outcome_not_documented")
        elif _after_any(referred, indications):
            path = "referred_no_outcome"
            followup_management = "intended_surgery_not_completed"
            confidence = "medium"
            classification_rule = "surgical_indication_with_referral_only"
            primary = _latest(_after_any(referred, indications))
            review_reasons.append("surgical_indication_present_but_terminal_outcome_not_documented")
        else:
            path = "surgery_indication_documented_outcome_unclear"
            followup_management = "intended_surgery_not_completed"
            confidence = "medium"
            classification_rule = "surgical_indication_without_documented_terminal_outcome"
            primary = latest_intent
            review_reasons.append("surgical_indication_present_but_terminal_outcome_not_documented")
    elif explicit_not_done:
        path = "aaoca_not_treated_indication_unclear"
        outcome = "no_aaoca_surgery_documented"
        followup_management = "pending_or_unresolved"
        confidence = "medium"
        classification_rule = "explicit_nonperformance_without_clear_indication_axis"
        primary = _latest(explicit_not_done)
        review_reasons.append("nonperformance_documented_but_surgical_indication_unclear")
    elif conservative or pending or referred or actual_amas:
        terminal_candidates = [
            *[(row, 1, "conservative") for row in conservative],
            *[(row, 3, "pending") for row in pending],
            *[(row, 2, "referred") for row in referred],
            *[(row, 4, "ama") for row in actual_amas],
        ]
        primary, _, terminal_kind = max(
            terminal_candidates,
            # On the same encounter date an unresolved examination/discussion
            # or a surgical referral is more specific than the templated line
            # "出院随访心内科" that usually appears later on the same page.
            # A genuinely later dated encounter still takes precedence.
            key=lambda item: (
                item[0].get("evidence_date", "") or "0000-00-00",
                item[1],
                _event_key(item[0])[1:],
            ),
        )
        if terminal_kind == "conservative":
            path = "clinician_conservative_other"
            outcome = "conservative_followup"
            followup_management = "conservative"
            confidence = "medium"
            classification_rule = "affirmative_aaoca_followup_or_medical_management"
            review_reasons.append("conservative_path_without_explicit_no_indication_statement")
        elif terminal_kind == "pending":
            path = "continued_evaluation_or_pending"
            confidence = "medium"
            classification_rule = "continued_evaluation_without_terminal_decision"
            review_reasons.append("terminal_management_decision_not_documented")
        elif terminal_kind == "ama":
            path = "left_against_medical_advice_outcome_unclear"
            confidence = "medium"
            classification_rule = "actual_ama_without_aaoca_specific_terminal_decision"
            review_reasons.append("left_against_medical_advice_without_aaoca_specific_outcome")
        else:
            path = "referred_no_outcome"
            confidence = "medium"
            classification_rule = "referral_without_terminal_outcome"
            review_reasons.append("post_referral_outcome_not_documented")
    elif source.get("other_cardiac_procedure_status") == "completed_other_cardiac_procedure":
        path = "other_cardiac_procedure_aaoca_handling_unresolved"
        confidence = "low"
        classification_rule = "completed_other_cardiac_procedure_without_resolved_aaoca_handling"
        review_reasons.append("aaoca_handling_during_other_cardiac_procedure_unresolved")
    elif source.get("other_cardiac_procedure_status") == "diagnostic_only_documented":
        path = "diagnostic_workup_terminal_decision_unresolved"
        confidence = "low"
        classification_rule = "diagnostic_workup_without_terminal_aaoca_management_decision"
        review_reasons.append("diagnostic_workup_completed_but_terminal_decision_not_documented")
    else:
        review_reasons.append("terminal_management_decision_not_found")

    if complex_status == "suspected":
        review_reasons.append("temporary_exclusion_requires_clinician_confirmation")
    if conflict_rows:
        review_reasons.append("earlier_and_later_management_evidence_conflict")
    if path in {
        "unclear",
        "continued_evaluation_or_pending",
        "referred_no_outcome",
        "left_against_medical_advice_outcome_unclear",
        "other_cardiac_procedure_aaoca_handling_unresolved",
        "diagnostic_workup_terminal_decision_unresolved",
        "surgery_indication_documented_outcome_unclear",
    }:
        review_reasons.append("followup_or_later_admission_query_recommended")

    supporting = []
    if primary:
        supporting.append(primary)
    supporting.extend(confirmed_conditions)
    if latest_intent:
        supporting.append(latest_intent)
    if latest_no_indication:
        supporting.append(latest_no_indication)
    supporting_ids = _serialize_list(row["evidence_id"] for row in supporting)
    conflict_ids = _serialize_list(row["evidence_id"] for row in conflict_rows)

    condition_rows = confirmed_conditions if confirmed_conditions else suspected_conditions
    condition_codes = _serialize_list(row["condition_code"] for row in condition_rows)
    condition_labels = _serialize_list(row["condition_label"] for row in condition_rows)
    condition_evidence_ids = _serialize_list(row["evidence_id"] for row in condition_rows)

    latest_decision = _latest(decisions)
    review_reasons = _serialize_list(review_reasons)
    review_required = bool(review_reasons)
    row = {
        "patient_id": source["patient_id"],
        "source_observed_management": source.get("observed_management", ""),
        "source_actual_aaoca_surgery": source.get("actual_aaoca_surgery", ""),
        "source_overall_treatment_status": source.get("overall_treatment_status", ""),
        "source_other_cardiac_procedure_status": source.get("other_cardiac_procedure_status", ""),
        "source_aaoca_handling_during_other_procedure": source.get("aaoca_handling_during_other_procedure", ""),
        "source_other_procedure_names": _json_list(source.get("unrelated_procedure_names")),
        "source_complex_case_review_priority": source.get("complex_case_review_priority", ""),
        "source_complex_case_review_reasons": source_complex_review_reasons,
        "source_primary_evidence_id": source.get("primary_evidence_id", ""),
        "source_primary_document_id": source.get("primary_document_id", ""),
        "source_primary_section_id": source.get("primary_section_id", ""),
        "source_primary_page_start": source.get("primary_page_start", ""),
        "source_primary_page_end": source.get("primary_page_end", ""),
        "source_primary_text_path": source.get("primary_text_path", ""),
        "source_primary_text_reference": source.get("primary_text_reference", ""),
        "complex_heart_disease_status": complex_status,
        "complex_condition_codes": condition_codes,
        "complex_condition_labels": condition_labels,
        "complex_condition_evidence_ids": condition_evidence_ids,
        "study_disposition": study_disposition,
        "surgery_indication": indication,
        "observed_aaoca_treatment_outcome": outcome,
        "decision_path": path,
        "followup_management": followup_management,
        "classification_confidence": confidence,
        "classification_rule": classification_rule,
        "latest_decision_date": (latest_decision or {}).get("evidence_date", ""),
        "primary_evidence_id": (primary or {}).get("evidence_id", ""),
        "primary_document_id": (primary or {}).get("document_id", ""),
        "primary_section_id": (primary or {}).get("section_id", ""),
        "primary_page_start": (primary or {}).get("page_start", ""),
        "primary_page_end": (primary or {}).get("page_end", ""),
        "primary_text_path": (primary or {}).get("text_path", ""),
        "primary_text_reference": (primary or {}).get("text_reference", ""),
        "primary_evidence_text": (primary or {}).get("evidence_text", ""),
        "supporting_evidence_ids": supporting_ids,
        "conflicting_evidence_ids": conflict_ids,
        "n_followup_evidence_rows": len(evidence),
        "review_required": review_required,
        "review_reasons": review_reasons,
    }

    for reason in review_reasons:
        severity = "high" if reason in {
            "terminal_management_decision_not_found",
            "conflicting_indication_evidence_chronology_unresolved",
            "surgical_indication_target_ambiguous",
        } else "medium"
        qc.append(
            {
                "patient_id": source["patient_id"],
                "decision_path": path,
                "issue_type": reason,
                "severity": severity,
                "evidence_ids": _serialize_list(
                    [
                        *condition_evidence_ids,
                        *supporting_ids,
                        *conflict_ids,
                        *[item["evidence_id"] for item in ambiguous_indications],
                    ]
                ),
                "detail": reason.replace("_", " "),
            }
        )
    return row, qc


def aggregate_followup(
    source_summaries: Iterable[dict],
    evidence: Iterable[dict],
) -> tuple[list[dict], list[dict]]:
    evidence_by_patient: dict[str, list[dict]] = defaultdict(list)
    for row in evidence:
        evidence_by_patient[row["patient_id"]].append(row)
    summaries: list[dict] = []
    qc: list[dict] = []
    for source in sorted(source_summaries, key=lambda row: row["patient_id"]):
        row, patient_qc = _classify_patient(source, evidence_by_patient.get(source["patient_id"], []))
        summaries.append(row)
        qc.extend(patient_qc)
    return summaries, qc


def _package_readme() -> str:
    return """# AAOCA unresolved-management follow-up package

This restricted local package is downstream of the validated Management output.
It does not alter source records or overwrite the original management fields.

- `followup_summary.csv`: one row per source `observed_management=unknown` patient.
- `followup_evidence.csv`: exact source spans used by the follow-up rules.
- `qc/review_queue.csv`: cases needing clinical review or later-record retrieval.
- `effective_rules.json`: the complete deterministic rules used for this run.
- `run_metadata.json`: input hashes, counts, code hash and validation receipt.

Interpret the axes separately:

- `study_disposition` records whether another confirmed complex cardiac disease
  temporarily removes the case from the AAOCA-isolated research cohort.
- `surgery_indication` records the treating team's documented recommendation.
- `observed_aaoca_treatment_outcome` records what is actually documented.
- `decision_path` combines those axes only for review and stratification.

`no_aaoca_surgery_documented` is an encounter/documented outcome.  It is not a
claim that the patient never underwent surgery anywhere or at a later date.
Plans, consent forms and diagnostic catheterisation do not establish completed
AAOCA surgery.  Suspected or differential diagnoses are never auto-excluded.
"""


def write_followup_package(
    run_root: Path,
    management_root: Path,
    output: Path,
    rules_path: Path | None = None,
) -> dict:
    run_root = run_root.resolve()
    management_root = management_root.resolve()
    output = output.resolve()
    for source_root in (run_root, management_root):
        if output == source_root or source_root in output.parents:
            raise ValueError("Follow-up output must be separate from every input directory")

    rules = load_rules(rules_path.resolve() if rules_path else None)
    source_rows = _read_csv(management_root / "management_summary.csv")
    unknown_rows = [row for row in source_rows if row.get("observed_management") == "unknown"]
    patient_ids = {row["patient_id"] for row in unknown_rows}
    if len(patient_ids) != len(unknown_rows):
        raise ValueError("Source unknown cohort contains duplicate patient_id rows")
    sections = load_sections(run_root, patient_ids)
    evidence = extract_followup_evidence(sections, rules)
    summaries, qc = aggregate_followup(unknown_rows, evidence)

    serializable_evidence = [{key: value for key, value in row.items() if not key.startswith("_")} for row in evidence]
    write_csv(output / "followup_summary.csv", summaries, SUMMARY_FIELDS)
    write_csv(output / "followup_evidence.csv", serializable_evidence, EVIDENCE_FIELDS)
    write_csv(output / "qc" / "review_queue.csv", qc, REVIEW_FIELDS)
    write_json(output / "effective_rules.json", rules)
    write_text(output / "README.md", _package_readme())

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "method": "deterministic_rules",
        "source_run": str(run_root),
        "source_management": str(management_root),
        "source_selection": "observed_management=unknown",
        "contains_clinical_excerpts": True,
        "network_processing": False,
        "llm_invoked": False,
        "counts": {
            "source_management_patients": len(source_rows),
            "source_unknown_patients": len(unknown_rows),
            "sections_scanned": len(sections),
            "followup_evidence_rows": len(evidence),
            "review_queue_rows": len(qc),
            "complex_heart_disease_statuses": dict(Counter(row["complex_heart_disease_status"] for row in summaries)),
            "study_dispositions": dict(Counter(row["study_disposition"] for row in summaries)),
            "surgery_indications": dict(Counter(row["surgery_indication"] for row in summaries)),
            "observed_aaoca_treatment_outcomes": dict(Counter(row["observed_aaoca_treatment_outcome"] for row in summaries)),
            "decision_paths": dict(Counter(row["decision_path"] for row in summaries)),
            "followup_management": dict(Counter(row["followup_management"] for row in summaries)),
        },
        "source_hashes": {
            "run_metadata": sha256_file(run_root / "run_metadata.json"),
            "section_index": sha256_file(run_root / "section_index.csv"),
            "management_run_metadata": sha256_file(management_root / "run_metadata.json"),
            "management_summary": sha256_file(management_root / "management_summary.csv"),
            "management_evidence": sha256_file(management_root / "management_evidence.csv"),
        },
        "code_sha256": sha256_file(Path(__file__)),
        "effective_rules_sha256": sha256_file(output / "effective_rules.json"),
    }
    write_json(output / "run_metadata.json", metadata)
    validation = validate_followup_package(output, run_root, management_root)
    if validation["validation_status"] != "passed":
        raise ValueError(f"Generated follow-up package failed validation: {validation['errors'][:3]}")
    metadata["validation"] = validation
    return metadata


def validate_followup_package(
    output: Path,
    run_root: Path | None = None,
    management_root: Path | None = None,
) -> dict:
    output = output.resolve()
    errors: list[dict] = []
    warnings: list[dict] = []
    required = [
        output / "followup_summary.csv",
        output / "followup_evidence.csv",
        output / "qc" / "review_queue.csv",
        output / "effective_rules.json",
        output / "run_metadata.json",
        output / "README.md",
    ]
    for path in required:
        if not path.is_file():
            errors.append({"code": "missing_output_file", "path": str(path)})
    if errors:
        return {
            "validation_status": "failed",
            "error_count": len(errors),
            "warning_count": 0,
            "errors": errors,
            "warnings": warnings,
        }

    summaries = _read_csv(output / "followup_summary.csv")
    evidence = _read_csv(output / "followup_evidence.csv")
    qc = _read_csv(output / "qc" / "review_queue.csv")
    metadata = json.loads((output / "run_metadata.json").read_text(encoding="utf-8"))

    patient_ids = [row.get("patient_id", "") for row in summaries]
    if not patient_ids or len(patient_ids) != len(set(patient_ids)):
        errors.append({"code": "missing_or_duplicate_summary_patient_id"})
    evidence_ids = [row.get("evidence_id", "") for row in evidence]
    if any(not value for value in evidence_ids) or len(evidence_ids) != len(set(evidence_ids)):
        errors.append({"code": "missing_or_duplicate_evidence_id"})
    evidence_by_id = {row["evidence_id"]: row for row in evidence if row.get("evidence_id")}

    for row in summaries:
        patient_id = row.get("patient_id", "")
        if row.get("complex_heart_disease_status") not in COMPLEX_STATUS_VALUES:
            errors.append({"code": "invalid_complex_status", "patient_id": patient_id})
        if row.get("study_disposition") not in STUDY_DISPOSITION_VALUES:
            errors.append({"code": "invalid_study_disposition", "patient_id": patient_id})
        if row.get("surgery_indication") not in SURGERY_INDICATION_VALUES:
            errors.append({"code": "invalid_surgery_indication", "patient_id": patient_id})
        if row.get("observed_aaoca_treatment_outcome") not in OUTCOME_VALUES:
            errors.append({"code": "invalid_treatment_outcome", "patient_id": patient_id})
        if row.get("decision_path") not in DECISION_PATH_VALUES:
            errors.append({"code": "invalid_decision_path", "patient_id": patient_id})
        if row.get("study_disposition") == "temporarily_excluded_complex_heart_disease" and row.get("complex_heart_disease_status") != "confirmed":
            errors.append({"code": "exclusion_without_confirmed_complex_disease", "patient_id": patient_id})
        if row.get("decision_path") == "clinician_no_indication_conservative":
            if row.get("surgery_indication") != "no" or row.get("observed_aaoca_treatment_outcome") != "conservative_followup":
                errors.append({"code": "no_indication_axis_mismatch", "patient_id": patient_id})
        if row.get("decision_path", "").startswith("surgery_indicated_not_done_"):
            if row.get("observed_aaoca_treatment_outcome") != "no_aaoca_surgery_documented":
                errors.append({"code": "indicated_not_done_outcome_mismatch", "patient_id": patient_id})
        primary_id = row.get("primary_evidence_id", "")
        if primary_id and primary_id not in evidence_by_id:
            errors.append({"code": "primary_evidence_not_found", "patient_id": patient_id, "evidence_id": primary_id})
        for field in ("complex_condition_evidence_ids", "supporting_evidence_ids", "conflicting_evidence_ids"):
            for evidence_id in _json_list(row.get(field)):
                if evidence_id not in evidence_by_id:
                    errors.append({"code": "referenced_evidence_not_found", "patient_id": patient_id, "field": field, "evidence_id": evidence_id})

    qc_patients = {row.get("patient_id", "") for row in qc}
    for row in summaries:
        if _bool(row.get("review_required")) and row["patient_id"] not in qc_patients:
            errors.append({"code": "review_required_without_queue_row", "patient_id": row["patient_id"]})

    if management_root is not None:
        management_root = management_root.resolve()
        source_unknown = {
            row["patient_id"]
            for row in _read_csv(management_root / "management_summary.csv")
            if row.get("observed_management") == "unknown"
        }
        if set(patient_ids) != source_unknown:
            errors.append(
                {
                    "code": "source_unknown_cohort_mismatch",
                    "missing": sorted(source_unknown - set(patient_ids)),
                    "extra": sorted(set(patient_ids) - source_unknown),
                }
            )
        expected_hashes = {
            "management_run_metadata": sha256_file(management_root / "run_metadata.json"),
            "management_summary": sha256_file(management_root / "management_summary.csv"),
            "management_evidence": sha256_file(management_root / "management_evidence.csv"),
        }
        for name, expected in expected_hashes.items():
            if metadata.get("source_hashes", {}).get(name) != expected:
                errors.append({"code": "source_hash_mismatch", "source": name})

    if run_root is not None:
        run_root = run_root.resolve()
        section_by_id: dict[str, dict] = {}
        for section in load_sections(run_root, set(patient_ids)):
            section_by_id[section["section_id"]] = section
        for row in evidence:
            section = section_by_id.get(row.get("section_id", ""))
            if section is None:
                errors.append({"code": "evidence_section_not_found", "evidence_id": row.get("evidence_id", "")})
                continue
            try:
                start = int(row.get("char_start", ""))
                end = int(row.get("char_end", ""))
            except ValueError:
                errors.append({"code": "invalid_evidence_span", "evidence_id": row.get("evidence_id", "")})
                continue
            if section.get("text", "")[start:end] != row.get("evidence_text", ""):
                errors.append({"code": "evidence_text_span_mismatch", "evidence_id": row.get("evidence_id", "")})
        expected_hashes = {
            "run_metadata": sha256_file(run_root / "run_metadata.json"),
            "section_index": sha256_file(run_root / "section_index.csv"),
        }
        for name, expected in expected_hashes.items():
            if metadata.get("source_hashes", {}).get(name) != expected:
                errors.append({"code": "source_hash_mismatch", "source": name})

    count_fields = {
        "source_unknown_patients": len(summaries),
        "followup_evidence_rows": len(evidence),
        "review_queue_rows": len(qc),
    }
    for name, actual in count_fields.items():
        if metadata.get("counts", {}).get(name) != actual:
            errors.append({"code": "metadata_count_mismatch", "field": name, "expected": actual})

    return {
        "validation_status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "patients": len(summaries),
        "evidence_rows": len(evidence),
        "review_queue_rows": len(qc),
        "decision_paths": dict(Counter(row.get("decision_path", "") for row in summaries)),
        "errors": errors,
        "warnings": warnings,
    }
