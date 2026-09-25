"""Small local I/O helpers; input files are always opened read-only.

Derived JSON/text use UTF-8. CSV uses a UTF-8 BOM for Windows/Excel, retains
identifiers as strings, and serializes list/dict values explicitly as JSON.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def write_csv(path: Path, rows: Iterable[dict], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(dict.fromkeys(k for row in rows for k in row))
    if not fields:
        fields = ["issue_type", "document_id", "patient_id", "detail"]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict))
                             else value for key, value in row.items()})
    os.replace(temporary, path)


def relative_output(path: Path, output: Path) -> str:
    return path.relative_to(output).as_posix()


def validate_output_locations(outputs: list[Path], raw_roots: list[Path], cohort_csv: Path) -> None:
    """Reject overlap in either direction, including symlinks/junctions.

    In particular an output cannot contain a raw root: a later cleanup must
    never be able to accidentally remove input data. The CSV directory is also
    protected. Config and output directories can live beside these raw inputs.
    """
    protected = [p.resolve() for p in raw_roots] + [cohort_csv.resolve().parent]
    for output in outputs:
        target = output.resolve()
        for raw in protected:
            if target == raw or target.is_relative_to(raw) or raw.is_relative_to(target):
                raise ValueError("Output/cache path overlaps a read-only input directory")
        # An existing nested link can otherwise redirect a derived artifact
        # into raw data despite a safe top-level output path. Inspect directory
        # entries only; do not follow linked trees or read patient contents.
        if output.exists():
            for directory, directories, filenames in os.walk(output, followlinks=False):
                for name in directories[:] + filenames:
                    child = Path(directory) / name
                    junction = getattr(child, "is_junction", lambda: False)()
                    if child.is_symlink() or junction:
                        resolved = child.resolve()
                        if any(resolved == raw or resolved.is_relative_to(raw) or raw.is_relative_to(resolved)
                               for raw in protected):
                            raise ValueError("An existing output/cache link overlaps a read-only input directory")
                        if name in directories:
                            directories.remove(name)
