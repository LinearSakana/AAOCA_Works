"""Conservative, local rules for the observed hospital PDF export templates.

This module does not infer clinical events. A dated section is a *document*
event, and a surgery-related title is not proof that an operation happened.
All normalized lines, including unknown preambles and damaged pages, belong
to exactly one section. ``page_spans`` use 1-based normalized-text line numbers;
their character offsets are 0-based, end-exclusive offsets in that page.
Raw extraction and normalization provenance remain in the extraction artifact.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import unicodedata
from typing import Any


# A full year is mandatory. Short dates are mentions, never silently completed.
_DATE_PATTERN = (
    r"(?<!\d)(?P<year>(?:19|20)\d{2})\s*[-/年.]\s*"
    r"(?P<month>\d{1,2})\s*[-/月.]\s*(?P<day>\d{1,2})日?"
    # OCR sometimes joins a two-digit day and two-digit hour (DDHH:MM).
    # The zero-width alternative is unambiguous only when both have 2 digits.
    r"(?:(?:[ T]+|(?<=\d{2})(?=\d{2}:))(?P<hour>\d{1,2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2}))?)?(?!\d)"
)
DATE_RE = re.compile(_DATE_PATTERN)
_UNUSABLE = {"empty", "failed", "text_layer_unusable"}
_DATE_FIELDS = re.compile(
    r"^(记录日期|记录时间|报告日期|报告时间|检验日期|检验时间|"
    r"检查日期|检查时间|就诊日期|会诊日期|会诊时间|讨论日期|讨论时间|"
    r"【讨论时间】|完成日期|出院日期)\s*[:：]?\s*"
)
_FILENAME_DATE = re.compile(r"(?<!\d)(?:19|20)\d{2}[-年.]\d{1,2}[-月.]\d{1,2}日?(?!\d)")
_LAB_APPLICATION = re.compile(r"^[\s•·●▪◦★☆\ue000-\uf8ff]{0,6}申请项目\s*[:：]\s*(?P<project>.*)$")
_OUTPATIENT_DATE = re.compile(r"^就诊日期\s*[:：]")
_HOSPITAL_HEADING = re.compile(r"^(?:上)?上海儿童[医醫區区]学中心$")


def _clean(text: str) -> str:
    """NFKC also restores Kangxi radicals used by the exported Chinese fonts."""
    return unicodedata.normalize("NFKC", text).strip()


def _dates(text: str) -> list[dict[str, Any]]:
    values = []
    for match in DATE_RE.finditer(text):
        parts = match.groupdict()
        try:
            value = datetime(
                int(parts["year"]), int(parts["month"]), int(parts["day"]),
                int(parts["hour"] or 0), int(parts["minute"] or 0), int(parts["second"] or 0),
            )
        except ValueError:
            continue
        precision = "second" if parts["second"] is not None else "minute" if parts["hour"] is not None else "day"
        values.append({
            "date": value.date().isoformat(),
            "timestamp": value.isoformat(timespec="seconds" if precision == "second" else "minutes") if parts["hour"] else "",
            "precision": precision, "start": match.start(), "end": match.end(),
        })
    return values


def _title_type(title: str, dated: bool = False) -> str | None:
    """Only title-shaped lines count; narrative keyword hits do not count."""
    title = _clean(title)
    if not title or len(title) > 60 or re.search(r"[\ue000-\uf8ff。;；:：]", title):
        return None
    if title.startswith(("请", "已", "详见", "参见", "参阅", "患者", "患儿", "本人", "完善")):
        return None
    # A leading icon denotes the web navigation, not a clinical record.
    if title.startswith("※"):
        return None
    if title.strip("()（）") in {"住院患者临时离院风险知情及责任承诺书", "防治新型冠状病毒家属入院承诺书"}:
        return "administrative"
    if re.search(r"(知情同意书|告知书|通知书|通知单|须知)$", title):
        return "administrative"
    if title in {"入院72小时内谈话记录", "入院24小时内谈话记录", "入院谈话记录"}:
        return "administrative"
    if title in {"入院记录", "再次入院记录", "入院病历", "24小时内入出院记录"}:
        return "admission"
    if title in {"出院记录", "出院小结", "出院总结"}:
        return "discharge"
    if re.fullmatch(r"(?:.{0,12})?(?:会诊记录|会诊意见|会诊[单単箪])", title):
        return "consultation"
    if title == "调整抗生素记录":
        return "progress"
    if re.fullmatch(r"术后.{0,16}病程(?:记录|录)", title):
        return "progress"
    if re.search(r"(?:术前|术后|手术|麻醉|操作).{0,18}(?:记录|讨论|小结|评估)(?:[（(].{0,16}[）)])?$", title):
        return "procedure"
    if "术前小结" in title and dated:
        return "procedure"
    if re.fullmatch(r"(?:.{0,10})?(?:超声报告|超声检查报告|超声检查报告单|心脏彩超报告)", title):
        return "ultrasound"
    if re.fullmatch(r"(?:.{0,12})?(?:检验报告|检验报告单|化验报告单)", title):
        return "laboratory"
    if title in {"门诊记录", "门诊病历", "急诊记录", "门诊就诊记录"}:
        return "outpatient"
    if title in {"随访记录", "随访病历", "随访报告", "门诊随访记录"}:
        return "follow_up"
    if dated and re.search(r"(?:病程|查房|病例讨论|抢救|转入|转出|交班|接班|抗生素使用)", title):
        # Short parenthetical template annotations are allowed, prose is not.
        if not re.search(r"[，,。]", title) and not any(x in title for x in ("患者", "患儿", "今日", "昨日", "辅助检查")):
            return "progress"
    if title in {"首次病程记录", "日常病程记录", "病程记录", "转入记录", "转出记录", "抢救记录", "死亡记录"}:
        return "progress"
    return None


def _header(line: dict[str, Any]) -> dict[str, Any] | None:
    value = _clean(line["text"])
    if line["unusable"]:
        return None
    # Lab exports concatenate multiple reports per page. Application item is
    # a report boundary; individual analyte rows are not separate documents.
    if _LAB_APPLICATION.match(value):
        return {"type_hint": "laboratory", "title": value, "kind": "lab_application"}
    ds = _dates(value)
    if ds and ds[0]["start"] == 0:
        after = value[ds[0]["end"]:].strip()
        kind = _title_type(after, dated=True)
        if kind:
            return {"type_hint": kind, "title": after, "kind": "dated_title", "date": ds[0]}
    kind = _title_type(value)
    if kind:
        return {"type_hint": kind, "title": value, "kind": "title"}
    return None


def _structured_outpatient_header(lines: list[dict[str, Any]], index: int,
                                  previous: dict[str, Any]) -> dict[str, Any] | None:
    """An outpatient form can start without a title; a dated repeat is a new visit."""
    if lines[index]["unusable"]:
        return None
    value = _clean(lines[index]["text"])
    if _HOSPITAL_HEADING.fullmatch(value):
        date_index = index + 1
    elif _OUTPATIENT_DATE.match(value):
        if index and _HOSPITAL_HEADING.fullmatch(_clean(lines[index - 1]["text"])):
            return None  # The hospital heading already owns this boundary.
        date_index = index
    else:
        return None
    if date_index >= len(lines) or not _OUTPATIENT_DATE.match(_clean(lines[date_index]["text"])):
        return None
    date_line = _clean(lines[date_index]["text"])
    visit_dates = _dates(date_line)
    if "就诊科室" not in date_line or not visit_dates:
        return None
    fields = set()
    for line in lines[date_index + 1:date_index + 36]:
        field_line = _clean(line["text"])
        if _OUTPATIENT_DATE.match(field_line):
            break
        for field in ("主诉", "现病史", "门诊初步诊断", "治疗计划"):
            if re.match(rf"^{field}\s*[:：]", field_line):
                fields.add(field)
    visit_date = visit_dates[0]
    marker = visit_date["timestamp"] or visit_date["date"]
    earlier = previous.get("date")
    earlier_marker = (earlier["timestamp"] or earlier["date"]) if earlier else ""
    new_visit = (previous["type_hint"] == "outpatient" and earlier_marker and marker != earlier_marker)
    if {"主诉", "现病史", "治疗计划"} <= fields or (new_visit and {"主诉", "现病史"} <= fields):
        return {"type_hint": "outpatient", "title": "", "kind": "structured_outpatient", "date": visit_date}
    return None


def _classify_type(header: dict[str, Any], lines: list[dict[str, Any]]) -> str:
    """Classify a finished block; known export chrome is not an unknown record."""
    if header["type_hint"] != "unknown":
        return header["type_hint"]
    values = [value for line in lines if (value := _clean(line["text"]))]
    if not values:
        return "nonclinical"
    if header["kind"] == "damaged_page":
        return "unknown"
    # Only institutional/demographic headers survived these damaged pages.
    header_line = re.compile(r"^(?:上海交通大学医学院附属上海儿童医学中心|Shanghai Children's Medical Cent|"
                             r"姓名[:：]|性别[:：]|自费器械耗材/药品/检验/检查|科别/床号[:：]|日期[:：])")
    if (header["kind"] == "continuation_after_damaged_page" and len(values) <= 8
            and all(header_line.match(value) for value in values)):
        return "nonclinical"
    if any("返回查询" in value or "VisitHistory/" in value or "BasicInfo/" in value for value in values):
        return "nonclinical"
    if len(values) <= 4 and any(re.fullmatch(r"动脉血\s*共\s*\d+\s*项", value) for value in values):
        return "nonclinical"
    return "unknown"


def _lab_markers(text: str) -> tuple[bool, set[str], bool]:
    """Read analyte labels, not incidental words elsewhere in a report."""
    gas_items = set()
    cardiac_items = set()
    heparin = False
    for raw_line in text.splitlines():
        value = _clean(raw_line)
        for item in ("pH", "PaCO2", "PaO2", "HCO3-", "Lac", "sO2", "ABE"):
            if re.match(rf"^{re.escape(item)}(?=$|[\s\d.<>↑↓])", value, re.I):
                gas_items.add(item)
        for item in ("NT-proBNP", "proBNP", "HS-CTNI", "CTNI", "BNP"):
            if re.match(rf"^{re.escape(item)}(?=$|[\s\d.<>↑↓])", value, re.I):
                cardiac_items.add(item)
        if re.match(r"^血浆肝素(?:含量)?(?=$|[\s\d.<>↑↓])", value):
            heparin = True
    gas = {"PaCO2", "PaO2"} <= gas_items and len(gas_items) >= 4
    return gas, cardiac_items, heparin


def _section_subtype(section_type: str, title: str, text: str) -> str:
    """Subtype is assigned after segmentation and cannot create a boundary."""
    title = _clean(title)
    if section_type == "progress":
        if "调整抗生素记录" in title:
            return "antibiotic_adjustment"
        if "术后" in title and "病程" in title:
            return "postop_progress"
        if "大型检查" in title and "病程" in title:
            return "procedure_imaging_progress"
        if "首次病程" in title:
            return "initial_progress"
        if "病例讨论" in title:
            return "case_discussion"
        if "查房" in title:
            if re.search(r"告病[危重]第?[一二三四五六七八九十\d]+天", title):
                return "critical_round"
            return "first_round" if "首次" in title else "round"
        if re.search(r"转[入出]记录", title):
            return "transfer"
        if "日常病程" in title:
            return "daily_progress"
        if title in {"病程记录", "病程录"} and all(field in text for field in ("病历特点", "鉴别诊断", "诊疗计划")):
            return "initial_progress"
    elif section_type == "administrative":
        if "生物样本" in title and "知情同意" in title:
            return "research_consent"
        if "住院患者临时离院风险知情及责任承诺书" in title:
            return "leave_commitment"
        if "防治新型冠状病毒家属入院承诺书" in title:
            return "infection_control_commitment"
        if "入院告知书" in title:
            return "admission_notice"
        if "谈话记录" in title or "病危" in title or "病重" in title or "病情告知" in title:
            return "condition_communication"
        if "知情同意书" in title and title not in {"知情同意书", "使用知情同意书"}:
            return "treatment_procedure_consent"
    elif section_type == "procedure":
        if "床旁超声" in title:
            return "bedside_ultrasound"
        if ("术前" in title or "术箭" in title) and "讨论" in title:
            return "preoperative_discussion"
        if "手术记录" in title and not title.startswith(("见", "⻅")):
            return "surgery_record"
        if "有创操作" in title or re.search(r"穿刺|置管|腰穿|骨穿|PICCO|PiCCO|IABP", title, re.I):
            return "invasive_procedure"
        if "操作记录" in title:
            return "procedure"
    elif section_type == "laboratory":
        gas, cardiac, heparin = _lab_markers(text)
        gas |= "血气" in title
        cardiac_present = bool(cardiac) or bool(re.search(r"CTNI|BNP|肌钙蛋白", title, re.I))
        heparin |= "肝素" in title
        if sum((gas, cardiac_present, heparin)) > 1:
            return "mixed_panel"
        if gas:
            return "blood_gas"
        if cardiac_present:
            return "cardiac_biomarker"
        if heparin:
            return "anticoagulation_monitoring"
    elif section_type == "outpatient":
        return "outpatient_record"
    elif section_type == "nonclinical":
        if not text.strip():
            return "empty_content"
        if re.match(r"^上海交通大学医学院附属上海儿童医学中心", text):
            return "document_header_only"
        if "返回查询" in text or "VisitHistory/" in text or "BasicInfo/" in text:
            return "web_navigation"
        if re.search(r"动脉血\s*共\s*\d+\s*项", text):
            return "lab_export_cover"
    return ""


def _section_title(header: dict[str, Any], section_type: str, subtype: str, text: str) -> str:
    """Extract a document name after type and subtype have been assigned."""
    title = _clean(header["title"])
    if section_type != "laboratory":
        if title.strip("()（）") in {"住院患者临时离院风险知情及责任承诺书", "防治新型冠状病毒家属入院承诺书"}:
            return title.strip("()（）")
        return re.sub(r"会诊[単箪]$", "会诊单", title) if section_type == "consultation" else title
    application = _LAB_APPLICATION.match(title)
    if application:
        project = re.sub(r"[,，]\s*\d+(?:\.\d+)?元$", "", application.group("project").strip())
        if project and project not in {"无数据", "-", "—"} and len(project) <= 80:
            return project
    elif title:
        return title  # A genuine 检验报告 heading is already an explicit title.
    gas, cardiac, heparin = _lab_markers(text)
    if subtype == "blood_gas" and gas:
        return "血气分析"
    if subtype == "cardiac_biomarker" and len(cardiac) == 1:
        return next(iter(cardiac))
    if subtype == "anticoagulation_monitoring" and heparin:
        if re.search(r"(?m)^血浆肝素含量(?:$|[\s\d.<>↑↓])", text):
            return "血浆肝素含量"
        if re.search(r"(?m)^血浆肝素(?:$|[\s\d.<>↑↓])", text):
            return "血浆肝素"
    return ""


def _flatten(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for ordinal, page in enumerate(pages, 1):
        page_number = int(page.get("page", ordinal))
        # The fallback is only for callers without the normalization module.
        content = page.get("normalized_text", page.get("text", "")) or ""
        status = page.get("extraction_status", "ok")
        from_ocr = page.get("analysis_text_source") == "local_ocr" and page.get("ocr_status") not in {"failed", "empty", "unavailable"}
        unusable = not from_ocr and (status in _UNUSABLE or bool(set(page.get("flags", [])) & {"vector_outlined_text_suspected", "text_layer_missing"}))
        lines = content.splitlines(keepends=True) or [""]
        line_map = page.get("normalized_line_map", [])
        chrome_removed = any(item.get("reason") in {"browser_title_at_page_margin", "browser_or_navigation_url"}
                             and item.get("raw_line", 999) <= 4 for item in page.get("removed_lines", []))
        offset = 0
        for number, chunk in enumerate(lines, 1):
            value = _clean(chunk)
            line_dates = _dates(value)
            raw_number = line_map[number - 1] if number <= len(line_map) else number
            # The browser print timestamp survives conservative normalization.
            # It is not a lab-result date even when a report spans two pages.
            margin_timestamp = (chrome_removed and raw_number <= 2 and len(line_dates) == 1
                                and line_dates[0]["start"] == 0 and line_dates[0]["end"] == len(value))
            result.append({"page": page_number, "line": number, "text": chunk.rstrip("\r\n"),
                           "char_start": offset, "char_end": offset + len(chunk),
                           "unusable": unusable, "from_ocr": from_ocr, "margin_timestamp": margin_timestamp,
                           "page_flags": page.get("flags", [])})
            offset += len(chunk)
    return result


def _role(text: str, position: int) -> str:
    """Mention roles prevent a birth/admission/print date being relabeled."""
    prefix = text[max(0, position - 20):position]
    for needle, role in (("出生", "birth"), ("打印", "print"), ("送样", "sample_submission"),
                         ("入院", "admission_mentioned"), ("出院", "discharge_mentioned"),
                         ("拟定手术", "planned_surgery"), ("拟行手术", "planned_surgery"),
                         ("手术", "surgery_mentioned"), ("记录", "record_field"),
                         ("检验", "test_field"), ("报告", "report_field")):
        if needle in prefix:
            return role
    return "content_mention"


def _date_for_section(lines: list[dict[str, Any]], header: dict[str, Any], section_type: str) -> tuple[dict[str, Any], list[str]]:
    blank = {"section_date": "", "document_date": "", "document_timestamp": "", "date_source": "unknown",
             "date_precision": "unknown", "date_evidence": "", "date_page": "", "date_line": "", "date_uncertain": True}
    if section_type in {"unknown", "nonclinical"} or any(line["unusable"] for line in lines):
        return blank, ["unknown_date"]
    candidates = []
    for idx, line in enumerate(lines):
        value = _clean(line["text"])
        ds = _dates(value)
        if not ds:
            continue
        parsed_header = _header(line)
        if idx < 20 and parsed_header and parsed_header.get("kind") == "dated_title":
            candidates.append((0, "title_timestamp", ds[0], line))
        field = _DATE_FIELDS.match(value)
        if field and len(value) <= 90 and len(ds) == 1:
            field_name = field.group(1)
            # Admission/discharge dates are facts inside a record. Only the
            # explicitly matching discharge document can use a discharge date.
            if field_name == "出院日期" and section_type != "discharge":
                continue
            if field_name.startswith("检查") and section_type not in {"ultrasound", "laboratory"}:
                continue
            if field_name == "就诊日期" and section_type != "outpatient":
                continue
            if field_name.startswith("会诊") and section_type != "consultation":
                continue
            if field_name.strip("【】").startswith("讨论") and section_type not in {"procedure", "progress"}:
                continue
            candidates.append((1, "explicit_field:" + field_name, ds[0], line))
    # Lab report exports have a 检验时间 column with repeated full timestamps.
    # Only a single unambiguous calendar date across the column is promoted.
    # A sample-submission date by itself does NOT establish a report date.
    if section_type == "laboratory" and any("检验时间" in _clean(l["text"]) for l in lines):
        standalone = []
        seen_column = False
        for line in lines:
            value = _clean(line["text"])
            if "检验时间" in value:
                seen_column = True
            ds = _dates(value)
            if seen_column and not line["margin_timestamp"] and len(ds) == 1 and ds[0]["start"] == 0 and ds[0]["end"] == len(value):
                standalone.append((ds[0], line))
        days = {date["date"] for date, _ in standalone}
        if len(days) == 1:
            dt, line = standalone[0]
            # Multiple row times: keep only supported day-level precision.
            if len({date["timestamp"] for date, _ in standalone}) > 1:
                dt = {**dt, "timestamp": "", "precision": "day"}
            candidates.append((2, "test_timestamp_column", dt, line))
        elif len(days) > 1:
            return blank, ["unknown_date", "conflicting_test_dates"]
    if not candidates:
        return blank, ["unknown_date"]
    priority = min(c[0] for c in candidates)
    best = [c for c in candidates if c[0] == priority]
    if len({c[2]["date"] for c in best}) > 1:
        return blank, ["unknown_date", "conflicting_document_dates"]
    _, source, dt, line = best[0]
    flags = []
    if len({c[2]["timestamp"] for c in best if c[2]["timestamp"]}) > 1:
        dt = {**dt, "timestamp": "", "precision": "day"}
        flags.append("conflicting_document_times")
    if any(c[2]["date"] != dt["date"] for c in candidates if c[0] > priority):
        flags.append("secondary_date_differs")
    if line["from_ocr"]:
        source = "local_ocr:" + source
        flags.append("date_requires_review")
    return {"section_date": dt["date"], "document_date": dt["date"], "document_timestamp": dt["timestamp"],
            "date_source": source, "date_precision": dt["precision"], "date_evidence": line["text"],
            "date_page": line["page"], "date_line": line["line"], "date_uncertain": False}, flags


def _spans(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans = []
    for line in lines:
        if not spans or spans[-1]["page"] != line["page"]:
            spans.append({"page": line["page"], "start_line": line["line"], "end_line": line["line"],
                          "start_char": line["char_start"], "end_char": line["char_end"]})
        else:
            spans[-1].update(end_line=line["line"], end_char=line["char_end"])
    return spans


def segment_document(pages: list[dict[str, Any]], source_pdf: str, patient_id: str = "", document_id: str = "") -> list[dict[str, Any]]:
    """Segment a PDF using observed headers, retaining complete line coverage.

    Dates are not inherited from neighboring sections or from navigation. A
    damaged page forces an unknown segment and prevents date propagation. The
    filename is a last-resort date only for one recognized section with no
    content dates, never for a multi-record export.
    """
    lines = _flatten(pages)
    if not lines:
        return []
    # Stage 1: detect boundaries only. The type here is a title-derived hint;
    # unknown export chrome is classified after each block has been cut.
    boundaries: list[tuple[int, dict[str, Any]]] = [(0, {"type_hint": "unknown", "title": "", "kind": "preamble"})]
    for index, line in enumerate(lines):
        changed_damage = index > 0 and line["unusable"] != lines[index - 1]["unusable"]
        if changed_damage:
            boundaries.append((index, {"type_hint": "unknown", "title": "", "kind": "damaged_page" if line["unusable"] else "continuation_after_damaged_page"}))
        header = _header(line) or _structured_outpatient_header(lines, index, boundaries[-1][1])
        if not header:
            continue
        previous_index, previous = boundaries[-1]
        # Repeated plain/title+timestamp headers immediately surrounding the
        # same metadata block represent one record, not two clinical events.
        date_agrees = (previous.get("date") == header.get("date")
                       or previous["kind"] != "dated_title" or header["kind"] != "dated_title")
        repeated = (previous["type_hint"] == header["type_hint"] and previous["title"] == header["title"]
                    and index - previous_index <= 12 and previous["kind"] not in {"lab_application", "structured_outpatient"}
                    and date_agrees)
        if repeated:
            continue
        if index == boundaries[-1][0]:
            boundaries[-1] = (index, header)
        else:
            boundaries.append((index, header))
    result = []
    for ordinal, (start, header) in enumerate(boundaries, 1):
        end = boundaries[ordinal][0] if ordinal < len(boundaries) else len(lines)
        block = lines[start:end]
        # Stages 2-4: classify the finished block, then its role, then title.
        kind = _classify_type(header, block)
        dates, flags = _date_for_section(block, header, kind)
        if kind == "unknown":
            flags.append("unknown_document_type")
        if any(l["unusable"] for l in block):
            flags.append("unusable_text_layer")
        if any(l["from_ocr"] for l in block):
            flags.append("ocr_unverified")
        if header["kind"] == "continuation_after_damaged_page":
            flags.append("continuation_after_damaged_page")
        mentions = []
        for line in block:
            value = _clean(line["text"])
            for dt in _dates(value):
                mentions.append({"date": dt["date"], "timestamp": dt["timestamp"], "precision": dt["precision"],
                                 "page": line["page"], "line": line["line"], "evidence": line["text"],
                                 "role": "print" if line["margin_timestamp"] else _role(value, dt["start"]),
                                 "is_document_date_evidence": line["page"] == dates["date_page"] and line["line"] == dates["date_line"]})
        text = "\n".join(l["text"] for l in block)
        # Stage is based only on the title. Never promote a clinical treatment
        # outcome from this field; postoperative text can still leak outcomes.
        subtype = _section_subtype(kind, header["title"], text)
        title = _section_title(header, kind, subtype, text)
        stage = "preoperative" if "术前" in title else "postoperative" if "术后" in title else "discharge" if kind == "discharge" else "unknown"
        leakage = []
        if kind in {"procedure", "discharge"}:
            leakage.append("outcome_information_possible")
        if re.search(r"术后(?:第?\s*[一二三四五六七八九十\d]+\s*天)?|昨日[行已]|已[行完成].{0,20}手术", _clean(text)):
            leakage.append("postoperative_or_treatment_mention")
        result.append({
            "section_id": f"{document_id or 'document'}_s{ordinal:04d}", "document_id": document_id,
            "patient_id": patient_id, "source_pdf": source_pdf,
            "section_type": kind, "section_subtype": subtype, "section_title": title, **dates,
            "page_start": block[0]["page"], "page_end": block[-1]["page"],
            "line_start": block[0]["line"], "line_end": block[-1]["line"],
            "page_spans": _spans(block), "offset_basis": "normalized_text",
            "text": text, "mentioned_dates": mentions, "flags": sorted(set(flags)),
            "parse_status": "unusable_text_layer" if "unusable_text_layer" in flags else "uncertain" if flags else "ok",
            "clinical_stage": stage, "leakage_flags": leakage,
            "segmentation_rule": header["kind"],
        })
    recognized = [s for s in result if s["section_type"] not in {"unknown", "nonclinical"}]
    if len(recognized) == 1:
        section = recognized[0]
        filename_dates = [d for match in _FILENAME_DATE.finditer(Path(source_pdf).stem) for d in _dates(match.group())]
        if len(filename_dates) == 1 and not section["document_date"] and not section["mentioned_dates"]:
            date = filename_dates[0]
            section.update(section_date=date["date"], document_date=date["date"], date_source="filename", date_precision="day",
                           date_evidence=Path(source_pdf).name, date_page="", date_line="", date_uncertain=True)
            section["flags"] = sorted(set(section["flags"]) | {"filename_date_unconfirmed"})
    return result
