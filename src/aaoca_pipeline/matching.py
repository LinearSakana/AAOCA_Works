"""Read-only cohort loading and conservative patient/PDF association.

The input is a local, access-controlled research dataset. Names and original
identifiers stay in memory (and in the caller's explicitly private artifacts),
while issues and stable IDs contain no direct patient identifiers. A hash is
pseudonymisation, not anonymisation; raw PDFs/text remain sensitive.

Matching does not search arbitrary clinical prose for numbers or use fuzzy
names. Exact filename names are cross-checked against the hospital export's
stable ``/BasicInfo/<outpatient>/<inpatient>`` URL template or labelled header
fields. Conflicting known patients are quarantined, never silently merged.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
DEFAULT_COLUMNS = {
    "inpatient_id": "住院号", "outpatient_id": "门诊号", "name": "姓名",
    "expected_record": "病历", "expected_lab": "检验",
}
_MISSING = {"", "-", "--", "—", "无", "暂无", "未知", "未提供", "不详",
            "nan", "none", "null", "na", "n/a", "unknown"}
# These are absent-identifier conventions, not a blanket exclusion of repeated
# numbers. Other suspicious patterns are reported and retained for review.
_PLACEHOLDERS = {"0", "000000", "00000000", "999999", "99999999"}
_URL_IDS = re.compile(
    r"/(?:BasicInfo|Allergy|VisitHistory|DignosisHistory|SurgeryHistory|"
    r"Medication|MedicationRecord|NonMedication|Expense|LabTest|Rad|EMR|"
    r"EMROutDoc|Nursing|PathologyDetail|RopAppointMent|TreatmentFor|"
    r"TreatmentRecord)/(\d{4,16})/(\d{4,16})(?=[/\s\)])"
)
_HEADER_IDS = {
    # A blank label at the bottom of a page must not consume a timestamp on
    # the next page. Accept same-line values only, and exclude date tokens.
    "inpatient_id": re.compile(r"(?:住院号|住院编号|病案号)[ \t]*[:：]?[ \t]*([A-Za-z0-9]{4,24})(?![A-Za-z0-9./-])"),
    "outpatient_id": re.compile(r"(?:门诊号|门诊编号)[ \t]*[:：]?[ \t]*([A-Za-z0-9]{4,24})(?![A-Za-z0-9./-])"),
}


def _norm(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def normalize_identifier(value: Any) -> str:
    """Preserve meaningful leading zeros; treat explicit placeholders as absent."""
    value = _norm(value)
    # Spreadsheet formatting can also affect placeholders such as 0.0.
    value = re.sub(r"^(\d+)\.0$", r"\1", value)
    if value.lower() in _MISSING or value in _PLACEHOLDERS:
        return ""
    return value


def _digest(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _issue(issue_type: str, severity: str = "warning", **fields: Any) -> dict:
    return {"issue_type": issue_type, "severity": severity, **fields}


def load_cohort(csv_path: Path, columns: dict | None = None) -> dict:
    """Load every CSV row, report conflicts, and preserve original ID strings.

    Stable patient IDs use the unique inpatient ID, then unique outpatient ID,
    then name. For duplicate inpatient IDs, a disambiguating identity tuple is
    hashed so two conflicting source rows cannot silently become one patient.
    Completely identical rows are reported and retain a duplicate-row suffix.
    No row is dropped. ``csv_row`` is the actual 1-based physical header/row
    convention used by spreadsheet programs (the first data row is row 2).
    """
    csv_path = Path(csv_path)
    colmap = {**DEFAULT_COLUMNS, **(columns or {})}
    encoding = "utf-8-sig"
    try:
        text = csv_path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        encoding = "gb18030"
        text = csv_path.read_text(encoding=encoding)
    reader = csv.DictReader(text.splitlines())
    required = [colmap[key] for key in ("inpatient_id", "outpatient_id", "name")]
    missing = [column for column in required if column not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"Cohort CSV is missing configured columns: {missing}")
    rows = list(reader)
    patients, issues = [], []
    for row_number, row in enumerate(rows, start=2):
        patient = {
            "csv_row": row_number,
            "inpatient_id": normalize_identifier(row.get(colmap["inpatient_id"])),
            "outpatient_id": normalize_identifier(row.get(colmap["outpatient_id"])),
            "name": _norm(row.get(colmap["name"])),
            "expected_record": _norm(row.get(colmap["expected_record"])),
            "expected_lab": _norm(row.get(colmap["expected_lab"])),
        }
        for key in ("inpatient_id", "outpatient_id"):
            patient[f"has_{key}"] = bool(patient[key])
        patient["cohort_issue_types"] = []
        patients.append(patient)
    counts = {key: Counter(p[key] for p in patients if p[key])
              for key in ("inpatient_id", "outpatient_id", "name")}
    id_seen: Counter = Counter()
    for patient, source_row in zip(patients, rows):
        if patient["inpatient_id"] and counts["inpatient_id"][patient["inpatient_id"]] == 1:
            basis = "inpatient:" + patient["inpatient_id"]
        elif patient["outpatient_id"] and counts["outpatient_id"][patient["outpatient_id"]] == 1:
            basis = "outpatient:" + patient["outpatient_id"]
        else:
            basis = "identity:" + "|".join(patient[k] for k in ("inpatient_id", "outpatient_id", "name"))
        patient_id = "p_" + _digest(basis)
        id_seen[patient_id] += 1
        patient["patient_id"] = patient_id if id_seen[patient_id] == 1 else f"{patient_id}_duplicate_{id_seen[patient_id]}"
        for key in ("inpatient_id", "outpatient_id"):
            source_value = _norm(source_row.get(colmap[key]))
            if source_value and not patient[key]:
                issue_type = "placeholder_identifier"
                issues.append(_issue(issue_type, patient_id=patient["patient_id"], csv_row=patient["csv_row"], field=key,
                                     details="Source value is a documented missing-value placeholder."))
                patient["cohort_issue_types"].append(issue_type)
        if not patient["inpatient_id"] and not patient["outpatient_id"]:
            issues.append(_issue("missing_identifiers", patient_id=patient["patient_id"], csv_row=patient["csv_row"],
                                 details="No usable inpatient or outpatient identifier; stable identity relies on name."))
        if id_seen[patient_id] > 1:
            issues.append(_issue("duplicate_cohort_row", "error", patient_id=patient["patient_id"], csv_row=patient["csv_row"],
                                 details="Indistinguishable identity row retained with duplicate suffix."))
    for key, counter in counts.items():
        for value, count in counter.items():
            if count < 2:
                continue
            affected = [p for p in patients if p[key] == value]
            issue_type = "duplicate_cohort_name" if key == "name" else "identifier_conflict"
            for patient in affected:
                patient["cohort_issue_types"].append(issue_type)
            issues.append(_issue(issue_type, field=key, patient_id="|".join(p["patient_id"] for p in affected),
                                 csv_rows="|".join(str(p["csv_row"]) for p in affected),
                                 details=f"{count} cohort rows share this exact field; identifier value omitted from QC."))
    LOGGER.info("Loaded %d cohort rows with %d cohort issues", len(patients), len(issues))
    return {"patients": patients, "issues": issues, "encoding": encoding, "columns": colmap,
            "source_csv": str(csv_path.resolve()), "row_count": len(patients)}


def _lookup(patients: list[dict]) -> dict:
    indexes = {field: defaultdict(set) for field in ("inpatient_id", "outpatient_id", "name")}
    for patient in patients:
        for field, index in indexes.items():
            if patient.get(field):
                index[patient[field]].add(patient["patient_id"])
    return indexes


def _filename_name(path: Path) -> str:
    """The observed export convention is exact-name + hyphen + export title."""
    return re.split(r"[-－—_]", _norm(path.stem), maxsplit=1)[0].strip()


def _filename_identifiers(path: Path, indexes: dict) -> set[str]:
    # Exact complete numeric tokens only. Never match a substring of a longer
    # number or arbitrary digits anywhere in document body text.
    tokens = re.findall(r"(?<![A-Za-z0-9])\d{4,16}(?![A-Za-z0-9])", _norm(path.stem))
    return set().union(*(indexes[key].get(token, set()) for token in tokens
                         for key in ("inpatient_id", "outpatient_id"))) if tokens else set()


def match_file(path: Path, patients: list[dict], header_text: str = "") -> dict:
    """Return match metadata for one path; an optional header adds cross-checks."""
    path = Path(path)
    record = {"source_pdf": str(path.resolve()), "document_id": "doc_" + _digest(str(path.resolve()).casefold(), 20)}
    return finalize_match(record, patients, header_text)


def finalize_match(file_record: dict, patients: list[dict], header_text: str = "") -> dict:
    """Resolve filename evidence plus stable export-header identifiers.

    Call with the first extracted page, or the first few pages if the first is
    blank. URL identifiers can safely be scanned over all pages: their narrow
    route template cannot match ordinary measurements or clinical dates.
    Labelled identifier extraction is limited to the first 20,000 characters;
    it is supplementary evidence, not an arbitrary full-text digit search.

    Returns a *new* record. ``match_issues`` contains PHI-free local QC records.
    ``header_identifiers`` contains raw sensitive identifiers for traceability
    and should only be saved in access-controlled local artifacts.
    """
    record = dict(file_record)
    indexes = _lookup(patients)
    by_id = {p["patient_id"]: p for p in patients}
    path = Path(record["source_pdf"])
    name_token = _filename_name(path)
    name_candidates = set(indexes["name"].get(name_token, set()))
    numeric_candidates = _filename_identifiers(path, indexes)
    filename_candidates = name_candidates | numeric_candidates
    url_ids = {"inpatient_id": set(), "outpatient_id": set()}
    for outpatient, inpatient in _URL_IDS.findall(header_text or ""):
        url_ids["inpatient_id"].add(normalize_identifier(inpatient))
        url_ids["outpatient_id"].add(normalize_identifier(outpatient))
    url_ids = {key: values - {""} for key, values in url_ids.items()}
    labelled_ids = {
        field: {normalize_identifier(value) for value in pattern.findall((header_text or "")[:20_000])} - {""}
        for field, pattern in _HEADER_IDS.items()
    }
    # The export URL is the stable patient envelope. A document inside that
    # export may carry an earlier encounter's hospital ID or a truncated ID.
    # Such labels remain visible as QC evidence but do not overwrite the URL.
    header_ids = {field: url_ids[field] or labelled_ids[field] for field in url_ids}
    candidates = {field: set().union(*(indexes[field].get(value, set()) for value in values)) if values else set()
                  for field, values in header_ids.items()}
    inpatient_candidates = candidates["inpatient_id"]
    outpatient_candidates = candidates["outpatient_id"]
    # A shared outpatient identifier may refer to two cohort rows. A matching
    # inpatient identifier resolves that ambiguity without concealing it.
    labelled_candidates = [set().union(*(indexes[field].get(value, set()) for value in values))
                           for field, values in labelled_ids.items() if values]
    evidence_sets = [x for x in (name_candidates, numeric_candidates, inpatient_candidates, outpatient_candidates,
                                 *labelled_candidates) if x]
    all_candidates = set().union(*evidence_sets) if evidence_sets else set()
    intersection = set.intersection(*evidence_sets) if evidence_sets else set()
    issues: list[dict] = []
    fields = {"document_id": record.get("document_id", "")}
    hard_conflict = bool(evidence_sets and not intersection)
    multiple_headers = any(len(values) > 1 for values in header_ids.values())
    # Two distinct inpatient header IDs are unsafe even if one is absent from
    # the cohort. An 8-digit shared outpatient ID alone is not multi-patient.
    if multiple_headers:
        hard_conflict = True
        issues.append(_issue("multiple_header_identifiers", "error", **fields,
                             patient_id="|".join(sorted(all_candidates)),
                             details="Multiple distinct patient identifiers in the stable PDF header template."))
    selected = next(iter(intersection)) if len(intersection) == 1 and not hard_conflict else ""
    identifier_conflict = False
    for field in url_ids:
        if url_ids[field] and labelled_ids[field] and labelled_ids[field] - url_ids[field]:
            identifier_conflict = True
            issues.append(_issue("document_identifier_mismatch", **fields, patient_id=selected, field=field,
                                 details="A labelled document ID differs from the stable export URL; possible earlier encounter or truncated text. Original evidence retained."))
    if selected:
        patient = by_id[selected]
        for field, observed in header_ids.items():
            expected = patient.get(field, "")
            if observed and expected and expected not in observed:
                identifier_conflict = True
                issues.append(_issue("header_identifier_mismatch", "error" if field == "inpatient_id" else "warning",
                                     **fields, patient_id=selected, field=field,
                                     details="Header identifier differs from the corresponding CSV identifier."))
                if field == "inpatient_id":
                    hard_conflict = True
                    selected = ""
                    break
    if hard_conflict:
        status = "ambiguous"
        selected = ""
        issues.append(_issue("file_multiple_patients", "error", **fields,
                             patient_id="|".join(sorted(all_candidates)),
                             details="Filename and/or header identifier evidence disagrees; no patient assigned."))
    elif selected:
        status = "matched"
    elif len(intersection) > 1:
        status = "ambiguous"
        issues.append(_issue("file_multiple_patients", "error", **fields,
                             patient_id="|".join(sorted(intersection)),
                             details="Exact evidence cannot uniquely distinguish multiple cohort patients."))
    else:
        status = "unmatched"
        issues.append(_issue("unmatched_file", **fields, patient_id="",
                             details="No cohort patient has matching exact filename or stable-header evidence."))
    methods = []
    if selected in name_candidates:
        methods.append("filename_exact_name")
    if selected in numeric_candidates:
        methods.append("filename_exact_identifier")
    if selected in inpatient_candidates:
        methods.append("header_inpatient_id")
    if selected in outpatient_candidates:
        methods.append("header_outpatient_id")
    if selected and name_token and selected not in name_candidates and (inpatient_candidates or outpatient_candidates):
        issues.append(_issue("filename_name_mismatch", **fields, patient_id=selected,
                             details="Exact stable-header identifiers recovered a patient whose filename name does not match the CSV."))
    record.update({
        "patient_id": selected,
        "candidate_patient_ids": sorted(all_candidates),
        "match_status": status,
        "match_method": "+".join(methods) if methods else "none",
        "identifier_conflict": identifier_conflict or hard_conflict,
        "header_identifiers": {key: sorted(value) for key, value in header_ids.items()},
        "document_labelled_identifiers": {key: sorted(value) for key, value in labelled_ids.items()},
        "header_crosschecked": bool(header_ids["inpatient_id"] or header_ids["outpatient_id"]),
        "match_issues": issues,
    })
    return record


def scan_and_match(pdf_roots: list[Path], patients: list[dict]) -> dict:
    """Scan and hash PDF sources without modifying or deduplicating them away.

    Root order is canonical-source priority. Byte-identical copies remain in
    the inventory; ``duplicate_of`` points to the first source's document ID.
    Case-insensitive suffix handling finds .pdf and .PDF on every platform.
    Root overlap never yields a second record for the same absolute file.
    """
    files, issues = [], []
    seen_paths, canonical_hash = set(), {}
    for root in map(Path, pdf_roots):
        root = root.resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Configured PDF root does not exist: {root}")
        for path in sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"),
                           key=lambda p: str(p).casefold()):
            absolute = str(path.resolve())
            path_key = absolute.casefold()
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            record = match_file(path, patients)
            record.update({"relative_source": str(path.relative_to(root)), "source_root": str(root),
                           "sha256": "", "file_size": None, "mtime_ns": None,
                           "duplicate_of": "", "is_canonical": True, "scan_status": "success"})
            try:
                stat = path.stat()
                record.update(file_size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                record["sha256"] = digest.hexdigest()
                if record["sha256"] in canonical_hash:
                    record["duplicate_of"] = canonical_hash[record["sha256"]]
                    record["is_canonical"] = False
                    issues.append(_issue("duplicate_pdf", "info", document_id=record["document_id"],
                                         patient_id=record["patient_id"], duplicate_of=record["duplicate_of"],
                                         details="Exact SHA256 duplicate; retained in inventory, canonical source selected by root order."))
                else:
                    canonical_hash[record["sha256"]] = record["document_id"]
            except OSError as exc:
                record["scan_status"] = "failed"
                issues.append(_issue("file_read_failure", "error", document_id=record["document_id"],
                                     patient_id=record["patient_id"], details=type(exc).__name__))
            files.append(record)
    LOGGER.info("Scanned %d PDF sources (%d unique readable contents)", len(files), len(canonical_hash))
    return {"files": files, "issues": issues, "n_files": len(files), "n_unique_sha256": len(canonical_hash)}
