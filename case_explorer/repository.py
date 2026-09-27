from __future__ import annotations

import csv
import hashlib
import json
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


API_SCHEMA_VERSION = "aaoca_case_explorer_api_v1"
REQUIRED_TABLES: dict[str, set[str]] = {
    "patient_manifest.csv": {"patient_id"},
    "document_index.csv": {"patient_id", "document_id"},
    "section_index.csv": {
        "patient_id",
        "document_id",
        "section_id",
        "text_path",
    },
}
OPTIONAL_TABLES = ("patient_timeline.csv",)


class CompatibilityError(RuntimeError):
    """Raised when a directory is not a compatible completed pipeline snapshot."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompatibilityError(f"Expected a JSON object in {path}")
    return value


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            return [dict(row) for row in reader], columns
    except (OSError, csv.Error) as exc:
        raise CompatibilityError(f"Cannot read CSV {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return [str(value)]
    return parsed if isinstance(parsed, list) else [parsed]


def _counter_rows(counter: Counter[str], *, empty_label: str = "unknown") -> list[dict[str, Any]]:
    return [
        {"key": key or empty_label, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0] or empty_label))
    ]


def _safe_relative_path(root: Path, raw: str) -> Path:
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise CompatibilityError(f"Referenced artifact escapes snapshot root: {raw}") from exc
    return candidate


def _run_sort_key(metadata: dict[str, Any], path: Path) -> tuple[str, int]:
    return (str(metadata.get("finished_at") or metadata.get("started_at") or ""), path.stat().st_mtime_ns)


@dataclass(frozen=True)
class RunDescriptor:
    key: str
    path: Path
    pipeline_version: str
    run_id: str
    finished_at: str
    status: str
    counts: dict[str, Any]

    def to_public(self, *, active: bool) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.path.name,
            "pipeline_version": self.pipeline_version,
            "run_id": self.run_id,
            "finished_at": self.finished_at,
            "status": self.status,
            "counts": self.counts,
            "active": active,
        }


@dataclass(frozen=True)
class SidecarBundle:
    path: Path
    metadata: dict[str, Any]
    summaries: dict[str, dict[str, str]]
    events: dict[str, list[dict[str, str]]]
    columns: dict[str, list[str]]


class SnapshotData:
    """Immutable in-memory view of one completed derived-data snapshot."""

    def __init__(
        self,
        run_path: Path,
        *,
        run_key: str,
        include_identifiers: bool,
        sidecar_root: Path | None,
    ) -> None:
        self.run_path = run_path.resolve()
        self.run_key = run_key
        self.include_identifiers = include_identifiers
        self.loaded_at = time.time()
        self.metadata = _read_json(self.run_path / "run_metadata.json")
        if self.metadata.get("status") != "complete":
            raise CompatibilityError(
                f"Snapshot {self.run_path} is not complete (status={self.metadata.get('status')!r})"
            )

        self.tables: dict[str, list[dict[str, str]]] = {}
        self.columns: dict[str, list[str]] = {}
        for filename, required_columns in REQUIRED_TABLES.items():
            path = self.run_path / filename
            if not path.is_file():
                raise CompatibilityError(f"Snapshot is missing required table: {path}")
            records, columns = _read_csv(path)
            missing = sorted(required_columns - set(columns))
            if missing:
                raise CompatibilityError(f"{filename} is missing required columns: {', '.join(missing)}")
            self.tables[filename] = records
            self.columns[filename] = columns

        for filename in OPTIONAL_TABLES:
            path = self.run_path / filename
            if path.is_file():
                records, columns = _read_csv(path)
            else:
                records, columns = [], []
            self.tables[filename] = records
            self.columns[filename] = columns

        self.patients = self.tables["patient_manifest.csv"]
        self.documents = self.tables["document_index.csv"]
        self.sections = self.tables["section_index.csv"]
        self.timeline = self.tables["patient_timeline.csv"]

        self.patient_by_id = {row["patient_id"]: row for row in self.patients}
        if len(self.patient_by_id) != len(self.patients):
            raise CompatibilityError("patient_manifest.csv contains duplicate patient_id values")

        self.documents_by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.document_by_id: dict[str, dict[str, str]] = {}
        for row in self.documents:
            self.documents_by_patient[row.get("patient_id", "")].append(row)
            document_id = row.get("document_id", "")
            if document_id and (document_id not in self.document_by_id or not row.get("duplicate_of")):
                self.document_by_id[document_id] = row

        self.sections_by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.section_by_id: dict[str, dict[str, str]] = {}
        for row in self.sections:
            section_id = row.get("section_id", "")
            if not section_id:
                raise CompatibilityError("section_index.csv contains an empty section_id")
            if section_id in self.section_by_id:
                raise CompatibilityError(f"section_index.csv contains duplicate section_id: {section_id}")
            self.section_by_id[section_id] = row
            self.sections_by_patient[row.get("patient_id", "")].append(row)

        self.timeline_by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
        if self.timeline:
            for row in self.timeline:
                self.timeline_by_patient[row.get("patient_id", "")].append(row)
        else:
            self.timeline = self._derive_timeline()
            for row in self.timeline:
                self.timeline_by_patient[row.get("patient_id", "")].append(row)

        self.identities: dict[str, dict[str, str]] = {}
        linkage_path = self.run_path / "private" / "patient_linkage.csv"
        if include_identifiers and linkage_path.is_file():
            linkage, linkage_columns = _read_csv(linkage_path)
            self.columns["private/patient_linkage.csv"] = linkage_columns
            self.identities = {row.get("patient_id", ""): row for row in linkage if row.get("patient_id")}

        self.sidecar = self._load_management_sidecar(sidecar_root)
        self.patient_rows = self._build_patient_rows()
        self.overview = self._build_overview()

    def _derive_timeline(self) -> list[dict[str, str]]:
        derived: list[dict[str, str]] = []
        for section in self.sections:
            date = section.get("section_date") or section.get("document_timestamp") or section.get("document_date")
            section_type = section.get("section_type", "")
            if not date or section_type == "nonclinical":
                continue
            derived.append(
                {
                    "patient_id": section.get("patient_id", ""),
                    "date": date,
                    "date_precision": section.get("date_precision", ""),
                    "event_type": section_type,
                    "event_subtype": section.get("section_subtype", ""),
                    "document_id": section.get("document_id", ""),
                    "section_id": section.get("section_id", ""),
                    "page": section.get("page_start", ""),
                    "page_end": section.get("page_end", ""),
                    "date_source": section.get("date_source", ""),
                    "date_evidence": section.get("date_evidence", ""),
                    "text_source": section.get("text_source", ""),
                    "parse_status": section.get("parse_status", ""),
                    "date_requires_review": section.get("date_requires_review", ""),
                }
            )
        return sorted(derived, key=lambda row: (row.get("patient_id", ""), row.get("date", "")))

    def _load_management_sidecar(self, sidecar_root: Path | None) -> SidecarBundle | None:
        if sidecar_root is None or not sidecar_root.exists():
            return None
        expected = {
            "run_metadata": _sha256(self.run_path / "run_metadata.json"),
            "patient_manifest": _sha256(self.run_path / "patient_manifest.csv"),
            "section_index": _sha256(self.run_path / "section_index.csv"),
        }
        candidates: list[tuple[int, Path, dict[str, Any]]] = []
        for summary_path in sidecar_root.rglob("management_summary.csv"):
            directory = summary_path.parent
            metadata_path = directory / "run_metadata.json"
            if not metadata_path.is_file():
                continue
            try:
                metadata = _read_json(metadata_path)
            except CompatibilityError:
                continue
            source_hashes = metadata.get("source_hashes") or metadata.get("cohort", {}).get("source_hashes") or {}
            normalized = {
                "run_metadata": source_hashes.get("run_metadata") or source_hashes.get("source_run_metadata_sha256"),
                "patient_manifest": source_hashes.get("patient_manifest") or source_hashes.get("source_patient_manifest_sha256"),
                "section_index": source_hashes.get("section_index") or source_hashes.get("source_section_index_sha256"),
            }
            if normalized != expected:
                continue
            candidates.append((summary_path.stat().st_mtime_ns, directory, metadata))
        if not candidates:
            return None
        _, directory, metadata = max(candidates, key=lambda item: item[0])
        summaries, summary_columns = _read_csv(directory / "management_summary.csv")
        events_path = directory / "surgery_events.csv"
        events, event_columns = _read_csv(events_path) if events_path.is_file() else ([], [])
        event_map: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in events:
            event_map[row.get("patient_id", "")].append(row)
        return SidecarBundle(
            path=directory,
            metadata=metadata,
            summaries={row.get("patient_id", ""): row for row in summaries if row.get("patient_id")},
            events=dict(event_map),
            columns={"management_summary.csv": summary_columns, "surgery_events.csv": event_columns},
        )

    def _build_patient_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for patient in self.patients:
            patient_id = patient["patient_id"]
            sections = self.sections_by_patient.get(patient_id, [])
            documents = self.documents_by_patient.get(patient_id, [])
            events = self.timeline_by_patient.get(patient_id, [])
            type_counts = Counter(row.get("section_type") or "unknown" for row in sections)
            source_counts = Counter(row.get("text_source") or "unknown" for row in sections)
            undated = sum(not (row.get("section_date") or row.get("document_timestamp") or row.get("document_date")) for row in sections)
            review_dates = sum(_as_bool(row.get("date_requires_review")) is True for row in sections)
            management = self.sidecar.summaries.get(patient_id) if self.sidecar else None
            identity = self.identities.get(patient_id, {})
            display_name = identity.get("name") if self.include_identifiers else ""
            search_values = [patient_id]
            if self.include_identifiers:
                search_values.extend(
                    identity.get(key, "") for key in ("name", "inpatient_id", "outpatient_id")
                )
            rows.append(
                {
                    "patient_id": patient_id,
                    "display_name": display_name,
                    "parse_status": patient.get("parse_status") or "unknown",
                    "n_documents": sum(not row.get("duplicate_of") for row in documents),
                    "n_source_documents": len(documents),
                    "n_sections": len(sections),
                    "n_timeline_events": len(events),
                    "earliest_date": patient.get("earliest_document_date") or "",
                    "latest_date": patient.get("latest_document_date") or "",
                    "section_types": dict(type_counts),
                    "text_sources": dict(source_counts),
                    "undated_sections": undated,
                    "date_review_sections": review_dates,
                    "management": management.get("observed_management", "") if management else "",
                    "actual_aaoca_surgery": management.get("actual_aaoca_surgery", "") if management else "",
                    "management_confidence": management.get("management_confidence", "") if management else "",
                    "review_required": _as_bool(management.get("review_required")) if management else None,
                    "_search": "\n".join(search_values).casefold(),
                    "_raw": patient,
                }
            )
        return rows

    def _build_overview(self) -> dict[str, Any]:
        canonical_documents = [row for row in self.documents if not row.get("duplicate_of")]
        section_type_counts = Counter(row.get("section_type") or "unknown" for row in self.sections)
        section_type_patients: dict[str, set[str]] = defaultdict(set)
        section_type_dated = Counter()
        for row in self.sections:
            key = row.get("section_type") or "unknown"
            section_type_patients[key].add(row.get("patient_id", ""))
            if row.get("section_date") or row.get("document_timestamp") or row.get("document_date"):
                section_type_dated[key] += 1
        section_types = [
            {
                "key": key,
                "count": count,
                "patients": len(section_type_patients[key] - {""}),
                "dated": section_type_dated[key],
            }
            for key, count in sorted(section_type_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        timeline_years = Counter()
        for row in self.timeline:
            date = row.get("date", "")
            if len(date) >= 4 and date[:4].isdigit():
                timeline_years[date[:4]] += 1
        management_counts = Counter()
        surgery_counts = Counter()
        if self.sidecar:
            for row in self.sidecar.summaries.values():
                management_counts[row.get("observed_management") or "unknown"] += 1
                surgery_counts[row.get("actual_aaoca_surgery") or "unknown"] += 1

        summary = self.metadata.get("summary", {})
        return {
            "totals": {
                "patients": len(self.patients),
                "patients_with_documents": sum(row["n_documents"] > 0 for row in self.patient_rows),
                "source_documents": len(self.documents),
                "canonical_documents": len(canonical_documents),
                "pages": sum(_as_int(row.get("page_count")) for row in canonical_documents),
                "sections": len(self.sections),
                "timeline_events": len(self.timeline),
            },
            "section_types": section_types,
            "patient_parse_statuses": _counter_rows(Counter(row["parse_status"] for row in self.patient_rows)),
            "document_parse_statuses": _counter_rows(
                Counter((row.get("parse_status") or "unknown") for row in canonical_documents)
            ),
            "section_parse_statuses": _counter_rows(
                Counter((row.get("parse_status") or "unknown") for row in self.sections)
            ),
            "text_sources": _counter_rows(Counter((row.get("text_source") or "unknown") for row in self.sections)),
            "timeline_years": [
                {"key": year, "count": timeline_years[year]} for year in sorted(timeline_years)
            ],
            "management_statuses": _counter_rows(management_counts) if self.sidecar else [],
            "surgery_statuses": _counter_rows(surgery_counts) if self.sidecar else [],
            "quality": {
                "sections_without_reliable_date": sum(
                    not (row.get("section_date") or row.get("document_timestamp") or row.get("document_date"))
                    for row in self.sections
                ),
                "sections_requiring_date_review": sum(
                    _as_bool(row.get("date_requires_review")) is True for row in self.sections
                ),
                "patients_without_documents": sum(row["n_documents"] == 0 for row in self.patient_rows),
                "source_hash_verification": summary.get("source_hash_verification") or "unknown",
                "uncovered_nonempty_lines": summary.get("uncovered_nonempty_lines"),
                "overlapping_nonempty_lines": summary.get("overlapping_nonempty_lines"),
            },
        }

    def _document_public(self, row: dict[str, str]) -> dict[str, Any]:
        document_id = row.get("document_id", "")
        if self.include_identifiers:
            label = Path(row.get("source_pdf") or row.get("relative_source") or document_id).name
        else:
            kind = row.get("document_type") or "document"
            label = f"{kind} · {document_id[-8:]}"
        known = {
            "patient_id",
            "document_id",
            "source_pdf",
            "relative_source",
            "source_root",
            "sha256",
            "file_size",
            "mtime_ns",
            "match_status",
            "match_method",
            "candidate_patient_ids",
            "duplicate_of",
            "page_count",
            "document_type",
            "document_date",
            "date_status",
            "earliest_section_date",
            "latest_section_date",
            "n_sections",
            "parse_status",
            "raw_parse_status",
            "extractor",
            "flags",
            "raw_text_path",
            "text_path",
            "sections_path",
            "ocr_attempted_page_count",
            "ocr_recovered_page_count",
            "ocr_character_count",
        }
        extra = {key: value for key, value in row.items() if key not in known and value not in (None, "")}
        return {
            "document_id": document_id,
            "label": label,
            "document_type": row.get("document_type") or "unknown",
            "document_date": row.get("document_date") or "",
            "earliest_section_date": row.get("earliest_section_date") or "",
            "latest_section_date": row.get("latest_section_date") or "",
            "page_count": _as_int(row.get("page_count")),
            "n_sections": _as_int(row.get("n_sections")),
            "parse_status": row.get("parse_status") or "unknown",
            "raw_parse_status": row.get("raw_parse_status") or "unknown",
            "text_source": "local_ocr" if _as_int(row.get("ocr_recovered_page_count")) else "pdf_text_layer",
            "ocr_recovered_pages": _as_int(row.get("ocr_recovered_page_count")),
            "flags": _json_list(row.get("flags")),
            "duplicate_of": row.get("duplicate_of") or "",
            "pdf_url": f"/api/documents/{document_id}/pdf" if row.get("source_pdf") else "",
            "relative_source": row.get("relative_source", "") if self.include_identifiers else "",
            "extra_fields": extra,
        }

    def _section_public(self, row: dict[str, str]) -> dict[str, Any]:
        return {
            "section_id": row.get("section_id", ""),
            "document_id": row.get("document_id", ""),
            "section_type": row.get("section_type") or "unknown",
            "section_subtype": row.get("section_subtype") or "",
            "title": row.get("section_title") or "",
            "date": row.get("section_date") or row.get("document_timestamp") or row.get("document_date") or "",
            "date_precision": row.get("date_precision") or "unknown",
            "date_source": row.get("date_source") or "",
            "date_requires_review": _as_bool(row.get("date_requires_review")),
            "page_start": _as_int(row.get("page_start")),
            "page_end": _as_int(row.get("page_end")),
            "parse_status": row.get("parse_status") or "unknown",
            "text_source": row.get("text_source") or "unknown",
            "clinical_stage": row.get("clinical_stage") or "unknown",
            "leakage_risk": row.get("leakage_risk") or "unreviewed",
            "cutoff_review_required": _as_bool(row.get("cutoff_review_required")),
            "flags": _json_list(row.get("flags")),
            "leakage_flags": _json_list(row.get("leakage_flags")),
        }

    def bootstrap(self, *, runs: list[dict[str, Any]], reload_error: str | None) -> dict[str, Any]:
        section_types = [row["key"] for row in self.overview["section_types"]]
        section_subtypes = sorted({row.get("section_subtype") for row in self.sections if row.get("section_subtype")})
        return {
            "api_schema_version": API_SCHEMA_VERSION,
            "snapshot": {
                "key": self.run_key,
                "label": self.run_path.name,
                "pipeline_version": self.metadata.get("pipeline_version") or "unknown",
                "run_id": self.metadata.get("run_id") or "",
                "started_at": self.metadata.get("started_at") or "",
                "finished_at": self.metadata.get("finished_at") or "",
                "loaded_at": self.loaded_at,
                "status": self.metadata.get("status"),
                "reload_error": reload_error,
            },
            "capabilities": {
                "identifiers_loaded": bool(self.identities),
                "management_sidecar": self.sidecar is not None,
                "timeline_source": "patient_timeline.csv" if self.columns["patient_timeline.csv"] else "derived_from_sections",
                "source_pdf": any(row.get("source_pdf") for row in self.documents),
                "hot_reload": True,
                "run_switching": len(runs) > 1,
            },
            "schema": {
                "tables": self.columns,
                "section_types": section_types,
                "section_subtypes": section_subtypes,
                "text_sources": [row["key"] for row in self.overview["text_sources"]],
                "patient_parse_statuses": [row["key"] for row in self.overview["patient_parse_statuses"]],
                "management_statuses": [row["key"] for row in self.overview["management_statuses"]],
            },
            "overview": self.overview,
            "runs": runs,
            "sidecar": {
                "label": self.sidecar.path.name if self.sidecar else "",
                "schema_version": self.sidecar.metadata.get("schema_version", "") if self.sidecar else "",
                "ruleset_version": self.sidecar.metadata.get("ruleset_version", "") if self.sidecar else "",
                "method": self.sidecar.metadata.get("method", "") if self.sidecar else "",
                "source_hash_match": True if self.sidecar else None,
            },
        }

    def list_patients(
        self,
        *,
        query: str = "",
        section_type: str = "",
        parse_status: str = "",
        management: str = "",
        review_required: str = "",
        sort: str = "latest_desc",
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        filtered: Iterable[dict[str, Any]] = self.patient_rows
        normalized_query = query.strip().casefold()
        if normalized_query:
            filtered = (row for row in filtered if normalized_query in row["_search"])
        if section_type:
            filtered = (row for row in filtered if row["section_types"].get(section_type, 0) > 0)
        if parse_status:
            filtered = (row for row in filtered if row["parse_status"] == parse_status)
        if management:
            filtered = (row for row in filtered if row["management"] == management)
        if review_required in {"true", "false"}:
            expected = review_required == "true"
            filtered = (row for row in filtered if row["review_required"] is expected)
        materialized = list(filtered)
        sorters = {
            "latest_desc": lambda row: (row["latest_date"], row["patient_id"]),
            "latest_asc": lambda row: (row["latest_date"] or "9999", row["patient_id"]),
            "sections_desc": lambda row: (row["n_sections"], row["patient_id"]),
            "sections_asc": lambda row: (row["n_sections"], row["patient_id"]),
            "patient_asc": lambda row: row["patient_id"],
        }
        if sort not in sorters:
            sort = "latest_desc"
        reverse = sort in {"latest_desc", "sections_desc"}
        materialized.sort(key=sorters[sort], reverse=reverse)
        total = len(materialized)
        offset = max(0, offset)
        limit = max(1, min(250, limit))
        page = materialized[offset : offset + limit]
        public_rows = [{key: value for key, value in row.items() if not key.startswith("_")} for row in page]
        return {"total": total, "offset": offset, "limit": limit, "rows": public_rows}

    def patient_detail(self, patient_id: str) -> dict[str, Any]:
        patient = self.patient_by_id.get(patient_id)
        if patient is None:
            raise KeyError(patient_id)
        documents = self.documents_by_patient.get(patient_id, [])
        sections = self.sections_by_patient.get(patient_id, [])
        timeline = self.timeline_by_patient.get(patient_id, [])
        section_public = [self._section_public(row) for row in sections]
        section_public.sort(key=lambda row: (row["date"] or "9999", row["page_start"], row["section_id"]))
        timeline_public = []
        for event in timeline:
            section = self.section_by_id.get(event.get("section_id", ""), {})
            merged = self._section_public(section) if section else {
                "section_id": event.get("section_id", ""),
                "document_id": event.get("document_id", ""),
                "section_type": event.get("event_type") or "unknown",
                "section_subtype": event.get("event_subtype") or "",
                "title": "",
                "date": event.get("date", ""),
                "date_precision": event.get("date_precision") or "unknown",
                "date_source": event.get("date_source", ""),
                "date_requires_review": _as_bool(event.get("date_requires_review")),
                "page_start": _as_int(event.get("page")),
                "page_end": _as_int(event.get("page_end")),
                "parse_status": event.get("parse_status") or "unknown",
                "text_source": event.get("text_source") or "unknown",
                "clinical_stage": event.get("clinical_stage") or "unknown",
                "leakage_risk": event.get("leakage_risk") or "unreviewed",
                "cutoff_review_required": _as_bool(event.get("cutoff_review_required")),
                "flags": _json_list(event.get("flags")),
                "leakage_flags": _json_list(event.get("leakage_flags")),
            }
            merged["date"] = event.get("date") or merged.get("date", "")
            timeline_public.append(merged)
        timeline_public.sort(key=lambda row: (row["date"], row["section_id"]))

        identity = self.identities.get(patient_id, {})
        identity_public = {
            key: identity.get(key, "")
            for key in ("name", "inpatient_id", "outpatient_id")
            if identity.get(key)
        }
        management = self.sidecar.summaries.get(patient_id) if self.sidecar else None
        events = self.sidecar.events.get(patient_id, []) if self.sidecar else []
        public_manifest = {
            key: value
            for key, value in patient.items()
            if key not in {"scope"} and value not in (None, "")
        }
        return {
            "patient_id": patient_id,
            "identity": identity_public,
            "manifest": public_manifest,
            "documents": [self._document_public(row) for row in documents],
            "sections": section_public,
            "timeline": timeline_public,
            "section_type_counts": _counter_rows(Counter(row["section_type"] for row in section_public)),
            "text_source_counts": _counter_rows(Counter(row["text_source"] for row in section_public)),
            "management": management or {},
            "surgery_events": events,
        }

    @lru_cache(maxsize=128)
    def section_detail(self, section_id: str) -> dict[str, Any]:
        index_row = self.section_by_id.get(section_id)
        if index_row is None:
            raise KeyError(section_id)
        path = _safe_relative_path(self.run_path, index_row.get("text_path", ""))
        payload = _read_json(path)
        candidates = payload.get("sections")
        if not isinstance(candidates, list):
            raise CompatibilityError(f"Section artifact has no sections array: {path}")
        section = next(
            (candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("section_id") == section_id),
            None,
        )
        if section is None:
            raise CompatibilityError(f"Section {section_id} is absent from {path}")
        known = {
            "section_id",
            "document_id",
            "patient_id",
            "source_pdf",
            "section_type",
            "section_subtype",
            "section_title",
            "section_date",
            "document_date",
            "document_timestamp",
            "date_source",
            "date_precision",
            "date_evidence",
            "date_page",
            "date_line",
            "date_uncertain",
            "page_start",
            "page_end",
            "line_start",
            "line_end",
            "page_spans",
            "offset_basis",
            "text",
            "mentioned_dates",
            "flags",
            "parse_status",
            "clinical_stage",
            "leakage_flags",
            "segmentation_rule",
            "text_path",
            "text_reference",
            "available_at",
            "cutoff_review_required",
            "text_source",
            "date_requires_review",
            "date_evidence_confidence",
            "leakage_risk",
        }
        extra = {key: value for key, value in section.items() if key not in known and value not in (None, "", [], {})}
        document_id = index_row.get("document_id", "")
        page_start = _as_int(index_row.get("page_start"))
        return {
            **self._section_public(index_row),
            "patient_id": index_row.get("patient_id", ""),
            "text": section.get("text") or "",
            "date_evidence": section.get("date_evidence") or "",
            "date_evidence_confidence": section.get("date_evidence_confidence"),
            "mentioned_dates": section.get("mentioned_dates") or [],
            "page_spans": section.get("page_spans") or [],
            "line_start": section.get("line_start"),
            "line_end": section.get("line_end"),
            "segmentation_rule": section.get("segmentation_rule") or "",
            "extra_fields": extra,
            "pdf_url": f"/api/documents/{document_id}/pdf#page={page_start}" if document_id else "",
        }

    def pdf_path(self, document_id: str) -> Path:
        row = self.document_by_id.get(document_id)
        if row is None or not row.get("source_pdf"):
            raise KeyError(document_id)
        path = Path(row["source_pdf"]).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        return path


class SnapshotRegistry:
    """Discovers compatible runs and atomically reloads the active snapshot."""

    def __init__(
        self,
        data_root: str | Path,
        *,
        run: str | Path | None = None,
        sidecar_root: str | Path | None = None,
        include_identifiers: bool = False,
        reload_interval: float = 2.0,
    ) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.requested_run = Path(run).expanduser().resolve() if run else None
        self.sidecar_root = Path(sidecar_root).expanduser().resolve() if sidecar_root else self.data_root
        self.include_identifiers = include_identifiers
        self.reload_interval = max(0.0, reload_interval)
        self._lock = threading.RLock()
        self._last_check = 0.0
        self._reload_error: str | None = None
        descriptors = self.discover_runs()
        if not descriptors:
            raise CompatibilityError(f"No compatible completed snapshots found under {self.data_root}")
        if self.requested_run:
            selected = next((item for item in descriptors if item.path == self.requested_run), None)
            if selected is None:
                raise CompatibilityError(f"Requested run is not a compatible completed snapshot: {self.requested_run}")
        else:
            selected = max(
                descriptors,
                key=lambda item: _run_sort_key(_read_json(item.path / "run_metadata.json"), item.path),
            )
        self._active_key = selected.key
        self._snapshot = self._load(selected)
        self._signature = self._current_signature(selected.path)

    def _descriptor(self, path: Path) -> RunDescriptor | None:
        metadata_path = path / "run_metadata.json"
        if not metadata_path.is_file():
            return None
        if not all((path / filename).is_file() for filename in REQUIRED_TABLES):
            return None
        try:
            metadata = _read_json(metadata_path)
        except CompatibilityError:
            return None
        if metadata.get("status") != "complete":
            return None
        try:
            key = path.relative_to(self.data_root).as_posix() or path.name
        except ValueError:
            key = path.name
        return RunDescriptor(
            key=key,
            path=path.resolve(),
            pipeline_version=str(metadata.get("pipeline_version") or "unknown"),
            run_id=str(metadata.get("run_id") or ""),
            finished_at=str(metadata.get("finished_at") or ""),
            status=str(metadata.get("status") or "unknown"),
            counts=dict(metadata.get("summary") or {}),
        )

    def discover_runs(self) -> list[RunDescriptor]:
        if self.requested_run:
            candidates = [self.requested_run]
        elif (self.data_root / "run_metadata.json").is_file():
            candidates = [self.data_root]
        elif self.data_root.exists():
            candidates = sorted({path.parent for path in self.data_root.rglob("run_metadata.json")})
        else:
            candidates = []
        descriptors = [descriptor for path in candidates if (descriptor := self._descriptor(path))]
        return sorted(descriptors, key=lambda item: (item.finished_at, item.key), reverse=True)

    def _load(self, descriptor: RunDescriptor) -> SnapshotData:
        return SnapshotData(
            descriptor.path,
            run_key=descriptor.key,
            include_identifiers=self.include_identifiers,
            sidecar_root=self.sidecar_root,
        )

    def _current_signature(self, run_path: Path) -> tuple[tuple[str, int, int], ...]:
        paths = [run_path / "run_metadata.json"]
        paths.extend(run_path / filename for filename in (*REQUIRED_TABLES, *OPTIONAL_TABLES))
        if self.include_identifiers:
            paths.append(run_path / "private" / "patient_linkage.csv")
        if self.sidecar_root.exists():
            for name in ("run_metadata.json", "management_summary.csv", "surgery_events.csv"):
                paths.extend(self.sidecar_root.rglob(name))
        signature = []
        for path in sorted(set(paths), key=lambda item: str(item).casefold()):
            try:
                stat = path.stat()
            except OSError:
                signature.append((str(path), -1, -1))
            else:
                signature.append((str(path), stat.st_size, stat.st_mtime_ns))
        return tuple(signature)

    def _maybe_reload(self) -> None:
        now = time.monotonic()
        if now - self._last_check < self.reload_interval:
            return
        self._last_check = now
        descriptor = next((item for item in self.discover_runs() if item.key == self._active_key), None)
        if descriptor is None:
            self._reload_error = f"Active snapshot is no longer a compatible completed run: {self._active_key}"
            return
        signature = self._current_signature(descriptor.path)
        if signature == self._signature:
            return
        try:
            replacement = self._load(descriptor)
        except Exception as exc:  # keep the last good snapshot available
            self._reload_error = f"Reload kept the last good snapshot: {exc}"
            return
        self._snapshot = replacement
        self._signature = signature
        self._reload_error = None

    def snapshot(self) -> SnapshotData:
        with self._lock:
            self._maybe_reload()
            return self._snapshot

    def runs_public(self) -> list[dict[str, Any]]:
        with self._lock:
            descriptors = self.discover_runs()
            return [item.to_public(active=item.key == self._active_key) for item in descriptors]

    def bootstrap(self) -> dict[str, Any]:
        with self._lock:
            self._maybe_reload()
            runs = self.runs_public()
            return self._snapshot.bootstrap(runs=runs, reload_error=self._reload_error)

    def select(self, run_key: str) -> dict[str, Any]:
        with self._lock:
            descriptor = next((item for item in self.discover_runs() if item.key == run_key), None)
            if descriptor is None:
                raise KeyError(run_key)
            replacement = self._load(descriptor)
            self._active_key = descriptor.key
            self._snapshot = replacement
            self._signature = self._current_signature(descriptor.path)
            self._reload_error = None
            self._last_check = time.monotonic()
            return self._snapshot.bootstrap(runs=self.runs_public(), reload_error=None)

    @property
    def reload_error(self) -> str | None:
        return self._reload_error

