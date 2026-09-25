"""Frozen, PDF-page anchored gold-set sampling and annotation contracts.

Everything created by this module stays under data/ (ignored by Git).  A page
is identified by its PDF content SHA256 and 1-based page number, never by a
parser-generated section ID.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import random
import re
import shutil

SCHEMA = "aao-gold-annotation/1"
SAMPLE_SCHEMA = "aao-gold-sample/1"
STRATA = ("native_record", "native_lab", "ocr_record", "ocr_lab")
TYPE_VALUES = {"admission", "administrative", "consultation", "discharge", "laboratory",
               "nonclinical", "outpatient", "procedure", "progress", "unknown"}
TYPE_STATUSES = {"known", "uncertain", "schema_gap"}
DATE_STATUSES = {"known", "absent", "uncertain", "schema_gap"}
DATE_ROLES = {"document", "test", "specimen", "performed_procedure", "other"}
OTHER_DATE_ROLES = DATE_ROLES | {"print", "historical", "planned_procedure"}
IMPACTS = {"low", "moderate", "high", "unknown"}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def complete_run(output: Path) -> dict:
    metadata = read_json(output / "run_metadata.json")
    if metadata.get("status") != "complete" or metadata.get("code_changed_during_run"):
        raise ValueError("A gold set requires a complete pipeline run with stable code")
    if metadata.get("summary", {}).get("source_hash_verification") != "passed":
        raise ValueError("A gold set requires a pipeline run with verified source hashes")
    return metadata


def source_documents(output: Path) -> dict[str, dict]:
    result = {}
    for doc in read_csv(output / "document_index.csv"):
        if doc["duplicate_of"] or not doc["sha256"]:
            continue
        if doc["sha256"] in result:
            raise ValueError("Duplicate canonical source hash")
        result[doc["sha256"]] = doc
    return result


def _candidate_tags(page: dict, sections: list[dict]) -> list[str]:
    tags = set()
    types = {s["section_type"] for s in sections}
    tags.update("type:" + kind for kind in types)
    if any(int(s["page_start"]) < int(page["page"]) < int(s["page_end"]) for s in sections):
        tags.add("cross_page")
    if sum(int(s["page_start"]) == int(page["page"]) for s in sections) > 1:
        tags.add("multiple_starts")
    if any(s["date_uncertain"].lower() in {"true", "1"} or not s["section_date"] for s in sections):
        tags.add("date_unknown_or_uncertain")
    if any(s["section_date"] for s in sections):
        tags.add("dated")
    if any("conflicting" in s["flags"] or "date_requires_review" in s["flags"] for s in sections):
        tags.add("date_conflict_or_review")
    if any("outcome_information_possible" in s["leakage_flags"] for s in sections):
        tags.add("possible_outcome_information")
    if int(page.get("ocr_low_confidence_line_count") or 0) > 0:
        tags.add("low_ocr_confidence")
    if int(page.get("normalized_character_count") or 0) == 0:
        tags.add("empty_text")
    if int(page.get("normalized_character_count") or 0) >= 1800:
        tags.add("dense_text")
    if "off_page_text" in page["flags"]:
        tags.add("off_page_text")
    return sorted(tags)


def sample(output: Path, destination: Path, pages_per_stratum: int = 12, seed: int = 20260925) -> dict:
    """Choose six routine and six difficult pages per stratum by default.

    Stable keyed randomness provides controls; greedy coverage across section
    types and difficulty tags provides difficult examples. A patient may
    contribute at most two pages, and a PDF at most two pages.
    """
    metadata = complete_run(output)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Refusing to replace a frozen sample: {destination}")
    docs = {d["document_id"]: d for d in source_documents(output).values()}
    section_pages = defaultdict(list)
    for row in read_csv(output / "section_index.csv"):
        for page in range(int(row["page_start"]), int(row["page_end"]) + 1):
            section_pages[(row["document_id"], page)].append(row)
    candidates = defaultdict(list)
    for page in read_csv(output / "page_index.csv"):
        doc = docs.get(page["document_id"])
        if not doc or not doc["patient_id"]:
            continue
        source = "ocr" if page["analysis_text_source"] == "local_ocr" else "native"
        family = "lab" if "检验" in doc["relative_source"] else "record"
        stratum = f"{source}_{family}"
        number = int(page["page"])
        item = {"unit_id": "pg_" + hashlib.sha256(f"{doc['sha256']}:{number}".encode()).hexdigest()[:16],
                "source_sha256": doc["sha256"], "page": number,
                "stratum": stratum, "tags": _candidate_tags(page, section_pages[(doc["document_id"], number)]),
                "baseline_document_id": doc["document_id"], "patient_id": doc["patient_id"]}
        candidates[stratum].append(item)
    rng = random.Random(seed)
    chosen, patient_counts, pdf_counts, tag_counts = [], Counter(), Counter(), Counter()
    for stratum in STRATA:
        pool = candidates[stratum]
        if len(pool) < pages_per_stratum:
            raise ValueError(f"Too few {stratum} pages for requested sample")
        # Random controls guard against a benchmark made entirely of known hard cases.
        shuffled = sorted(pool, key=lambda x: x["unit_id"])
        rng.shuffle(shuffled)
        random_order = {item["unit_id"]: index for index, item in enumerate(shuffled)}
        routine = sorted(shuffled, key=lambda x: (len(set(x["tags"]) - {"dated"}),
                                                   random_order[x["unit_id"]]))
        def eligible(item):
            return patient_counts[item["patient_id"]] < 2 and pdf_counts[item["source_sha256"]] < 2
        def take(item, arm):
            chosen.append({k: v for k, v in item.items() if k != "patient_id"} | {"sampling_arm": arm})
            patient_counts[item["patient_id"]] += 1
            pdf_counts[item["source_sha256"]] += 1
            tag_counts.update(item["tags"])
        for item in routine:
            if sum(x["stratum"] == stratum and x["sampling_arm"] == "routine" for x in chosen) >= pages_per_stratum // 2:
                break
            if eligible(item):
                take(item, "routine")
        while sum(x["stratum"] == stratum for x in chosen) < pages_per_stratum:
            options = [x for x in shuffled if eligible(x) and x["unit_id"] not in {y["unit_id"] for y in chosen}]
            if not options:
                raise ValueError(f"Patient/PDF caps made {stratum} quota impossible")
            # Global diminishing returns spread difficult cases and rare types.
            weights = {"multiple_starts": 5, "cross_page": 4, "date_unknown_or_uncertain": 3,
                       "date_conflict_or_review": 4, "low_ocr_confidence": 3,
                       "empty_text": 4, "off_page_text": 3, "dense_text": 2,
                       "possible_outcome_information": 2}
            def score(item):
                return sum((weights.get(t, 5 if t.startswith("type:") else 1) /
                            (1 + tag_counts[t])) for t in item["tags"])
            best = max(options, key=lambda x: (score(x), -random_order[x["unit_id"]]))
            take(best, "challenge")
    chosen.sort(key=lambda x: (STRATA.index(x["stratum"]), x["unit_id"]))
    manifest = {"schema_version": SAMPLE_SCHEMA, "sampling_version": "stratified_page_v1",
                "seed": seed, "pages_per_stratum": pages_per_stratum,
                "source_run": {"run_id": metadata["run_id"], "pipeline_version": metadata["pipeline_version"],
                               "code_sha256": metadata["code_sha256"],
                               "run_metadata_sha256": hashlib.sha256((output / "run_metadata.json").read_bytes()).hexdigest()},
                "units": chosen}
    manifest["sample_id"] = digest(manifest)[:20]
    write_json(destination / "manifest.json", manifest)
    (destination / "annotations").mkdir(parents=True, exist_ok=True)
    return manifest


def validate_annotation(annotation: dict, unit: dict, sample_id: str) -> list[str]:
    errors = []
    def fail(message):
        errors.append(message)
    if annotation.get("schema_version") != SCHEMA or annotation.get("unit_id") != unit["unit_id"]:
        fail("schema or unit mismatch")
    if annotation.get("source_sha256") != unit["source_sha256"] or annotation.get("page") != unit["page"]:
        fail("PDF anchor mismatch")
    if annotation.get("sample_id") != sample_id:
        fail("sample_id mismatch")
    status = annotation.get("status")
    if status not in {"draft", "complete", "unreviewable"}:
        fail("invalid review status")
    if status in {"complete", "unreviewable"} and not annotation.get("reviewer", "").strip():
        fail("completed review needs a reviewer name or pseudonym")
    if status == "unreviewable":
        if not annotation.get("notes", "").strip():
            fail("unreviewable page needs a reason")
        return errors
    text = annotation.get("text", {})
    if text.get("status") not in {"ok", "corrected", "uncertain"} or not isinstance(text.get("gold_text"), str):
        fail("text status and gold_text are required")
    if text.get("impact", "unknown") not in IMPACTS:
        fail("invalid text clinical impact")
    lines = text.get("gold_text", "").splitlines()
    sections = annotation.get("sections", [])
    if not isinstance(sections, list):
        return errors + ["sections must be a list"]
    if status == "draft":
        return errors
    occupied = []
    for index, section in enumerate(sections, 1):
        prefix = f"section {index}: "
        start, end = section.get("start_line"), section.get("end_line")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > len(lines):
            fail(prefix + "invalid line span")
            continue
        occupied.extend(range(start, end + 1))
        label = section.get("type", {})
        if label.get("status") not in TYPE_STATUSES or (label.get("status") == "known" and label.get("value") not in TYPE_VALUES):
            fail(prefix + "invalid type")
        sub = section.get("subtype", {})
        if sub.get("status") not in TYPE_STATUSES or (sub.get("status") == "known" and not isinstance(sub.get("value"), str)):
            fail(prefix + "invalid subtype")
        dt = section.get("date", {})
        if dt.get("status") not in DATE_STATUSES:
            fail(prefix + "invalid date status")
        elif dt["status"] == "known":
            try:
                date.fromisoformat(dt["value"])
            except (KeyError, TypeError, ValueError):
                fail(prefix + "invalid known date")
            if dt.get("role") not in DATE_ROLES:
                fail(prefix + "invalid event date role")
        elif dt.get("value"):
            fail(prefix + "nonknown date must have no value")
        for other in dt.get("other_dates", []):
            try:
                date.fromisoformat(other["value"])
            except (KeyError, TypeError, ValueError):
                fail(prefix + "invalid other date")
            if other.get("role") not in OTHER_DATE_ROLES:
                fail(prefix + "invalid other date role")
        if section.get("impact") not in IMPACTS:
            fail(prefix + "invalid clinical impact")
    nonempty = {i for i, line in enumerate(lines, 1) if line.strip()}
    if status == "complete" and (not nonempty.issubset(set(occupied)) or len(occupied) != len(set(occupied))):
        fail("complete annotation must cover each nonempty gold line exactly once")
    if status == "complete" and text.get("status") == "uncertain" and not annotation.get("notes", "").strip():
        fail("uncertain transcription needs an explanation")
    return errors


def load_annotations(gold_dir: Path, revision: str | None = None) -> tuple[dict, dict[str, dict]]:
    manifest = read_json(gold_dir / "manifest.json")
    if manifest.get("schema_version") != SAMPLE_SCHEMA:
        raise ValueError("Unsupported gold sample schema")
    if manifest.get("sample_id") != digest({k: v for k, v in manifest.items() if k != "sample_id"})[:20]:
        raise ValueError("Gold sample manifest digest does not match")
    directory = gold_dir / "revisions" / revision if revision else gold_dir / "annotations"
    annotations = {}
    for unit in manifest["units"]:
        path = directory / f"{unit['unit_id']}.json"
        if not path.exists():
            continue
        annotation = read_json(path)
        errors = validate_annotation(annotation, unit, manifest["sample_id"])
        if errors:
            raise ValueError(f"{path}: {'; '.join(errors)}")
        annotations[unit["unit_id"]] = annotation
    return manifest, annotations


def annotation_digest(annotations: dict[str, dict]) -> str:
    return digest({key: annotations[key] for key in sorted(annotations)})


def freeze(gold_dir: Path, revision: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", revision) or revision in {".", ".."}:
        raise ValueError("Revision must be a simple name")
    manifest, annotations = load_annotations(gold_dir)
    units = manifest["units"]
    if len(annotations) != len(units) or any(a["status"] not in {"complete", "unreviewable"} for a in annotations.values()):
        raise ValueError("Every sampled page must be complete or explicitly unreviewable")
    target = gold_dir / "revisions" / revision
    if target.exists():
        raise FileExistsError(f"Gold revision already exists: {target}")
    target.mkdir(parents=True)
    for unit in units:
        source = gold_dir / "annotations" / f"{unit['unit_id']}.json"
        shutil.copy2(source, target / source.name)
    receipt = {"revision": revision, "sample_id": manifest["sample_id"],
               "annotation_schema": SCHEMA, "annotation_digest": annotation_digest(annotations),
               "frozen_at": datetime.now().astimezone().isoformat(), "reviewed_pages": len(units),
               "unreviewable_pages": sum(a["status"] == "unreviewable" for a in annotations.values())}
    write_json(target / "freeze.json", receipt)
    return receipt
