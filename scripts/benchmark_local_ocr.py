"""Reproducible local PP-OCR model comparison on an explicit private case list.

Example (paths are local, and the case list is never uploaded):
  python -X utf8 scripts/benchmark_local_ocr.py --cases scratch/ocr_cases.json \
      --model-root models/ocr_benchmark --output scratch/ocr_benchmark \
      --versions v6 v5 v4 --download-models

Cases JSON: [{"case_id":"native_01", "source_pdf":"/local/file.pdf",
              "page":1, "group":"native_case"}].

The only permitted network step downloads PUBLIC model weights, before PDFs are
opened. All subsequent model loading and inference run with Python HTTP access
blocked. Summary CSV/JSON contain case aliases and aggregate metrics, not patient
identifiers or clinical text. Optional predictions remain local restricted data.

Native text is a silver reference, not medical ground truth. Only CJK characters
whose full bounding box lies on the visible page enter the reference. Geometry
matches reference characters to OCR lines; uncovered characters count as
deletions. OCR lines outside all native CJK boxes may contain visible image
labels and are counted separately, not treated as proven hallucinations. This is
a diagnostic CER proxy, not a validated OCR accuracy claim.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import fitz
import numpy as np
from rapidocr import ModelType, OCRVersion, RapidOCR

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
MODEL_SPECS = {
    "v6": {"version": "PP-OCRv6", "type": "small", "det": "PP-OCRv6_det_small.onnx", "rec": "PP-OCRv6_rec_small.onnx"},
    "v5": {"version": "PP-OCRv5", "type": "mobile", "det": "ch_PP-OCRv5_det_mobile.onnx", "rec": "ch_PP-OCRv5_rec_mobile.onnx"},
    "v4": {"version": "PP-OCRv4", "type": "mobile", "det": "ch_PP-OCRv4_det_mobile.onnx", "rec": "ch_PP-OCRv4_rec_mobile.onnx"},
}
CLS_MODEL = "ch_ppocr_mobile_v2.0_cls_mobile.onnx"


def engine_params(version: str, directory: Path, *, explicit: bool) -> dict:
    spec = MODEL_SPECS[version]
    params = {
        "Global.model_root_dir": str(directory.resolve()), "Global.log_level": "warning",
        "Global.use_cls": False, "EngineConfig.onnxruntime.intra_op_num_threads": 4,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "Det.ocr_version": OCRVersion(spec["version"]), "Rec.ocr_version": OCRVersion(spec["version"]),
        "Det.model_type": ModelType(spec["type"]), "Rec.model_type": ModelType(spec["type"]),
    }
    if explicit:
        for kind, filename in (("Det", spec["det"]), ("Rec", spec["rec"]), ("Cls", CLS_MODEL)):
            path = directory / filename
            if not path.is_file():
                raise FileNotFoundError(f"Missing public model: {filename}. Run with --download-models.")
            params[f"{kind}.model_path"] = str(path.resolve())
    return params


def visible_reference(page: fitz.Page) -> list[dict]:
    refs = []
    for block in page.get_text("rawdict", flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_MEDIABOX_CLIP, clip=fitz.INFINITE_RECT()).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    if CJK.fullmatch(char["c"]) and page.rect.contains(fitz.Rect(char["bbox"])):
                        bbox = char["bbox"]
                        refs.append({"char": char["c"], "x": (bbox[0] + bbox[2]) / 2, "y": (bbox[1] + bbox[3]) / 2})
    return refs


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, first in enumerate(left, 1):
        current = [i]
        for j, second in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (first != second)))
        previous = current
    return previous[-1]


def native_metrics(refs: list[dict], texts: list[str], boxes: list, scale: float) -> dict:
    """Geometry-aligned CJK errors + bag recall, exposing missed coverage."""
    if not refs:
        return {"native_reference_cjk": 0, "cjk_cer_proxy": None, "cjk_bag_recall": None, "cjk_detection_coverage": None, "unreferenced_ocr_cjk": None}
    assigned: set[int] = set()
    errors = 0
    unreferenced = 0
    for text, polygon in zip(texts, boxes):
        x0 = min(point[0] for point in polygon) / scale - 1
        x1 = max(point[0] for point in polygon) / scale + 1
        y0 = min(point[1] for point in polygon) / scale - 1
        y1 = max(point[1] for point in polygon) / scale + 1
        hits = [(i, ref) for i, ref in enumerate(refs) if i not in assigned and x0 <= ref["x"] <= x1 and y0 <= ref["y"] <= y1]
        hits.sort(key=lambda item: (round(item[1]["y"] / 3), item[1]["x"]))
        assigned.update(i for i, _ in hits)
        reference = "".join(ref["char"] for _, ref in hits)
        prediction = "".join(CJK.findall(text))
        if hits:
            errors += edit_distance(reference, prediction)
        else:
            unreferenced += len(prediction)
    errors += len(refs) - len(assigned)
    ref_counts = Counter(ref["char"] for ref in refs)
    predicted_counts = Counter(CJK.findall("".join(texts)))
    return {
        "native_reference_cjk": len(refs), "cjk_cer_proxy": round(errors / len(refs), 6),
        "cjk_bag_recall": round(sum((ref_counts & predicted_counts).values()) / len(refs), 6),
        "cjk_detection_coverage": round(len(assigned) / len(refs), 6),
        "unreferenced_ocr_cjk": unreferenced,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--versions", nargs="+", choices=MODEL_SPECS, default=["v6", "v5", "v4"])
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--download-models", action="store_true")
    parser.add_argument("--private-predictions", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Acquisition is performed before even reading the private case-list file.
    for version in args.versions:
        directory = args.model_root / version
        directory.mkdir(parents=True, exist_ok=True)
        if args.download_models:
            RapidOCR(params=engine_params(version, directory, explicit=False))
        engine_params(version, directory, explicit=True)

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    rows = []
    provenance = {}
    for version in args.versions:
        directory = args.model_root / version
        provenance[version] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.glob("*.onnx")}
        with patch("requests.sessions.Session.request", side_effect=RuntimeError("Network forbidden during patient inference")):
            engine = RapidOCR(params=engine_params(version, directory, explicit=True))
            for case in cases:
                with fitz.open(case["source_pdf"]) as document:
                    page = document[case["page"] - 1]
                    refs = visible_reference(page) if case["group"].startswith("native") else []
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(args.scale, args.scale), alpha=False)
                    pixels = np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
                started = time.monotonic()
                output = engine(pixels, use_cls=False)
                elapsed = time.monotonic() - started
                texts = list(output.txts) if output.txts is not None else []
                scores = [float(score) for score in output.scores] if output.scores is not None else []
                boxes = output.boxes.tolist() if output.boxes is not None else []
                row = {
                    "version": version, "case_id": case["case_id"], "group": case["group"],
                    "seconds": round(elapsed, 4), "cjk_characters": len(CJK.findall("".join(texts))),
                    "total_characters": sum(map(len, texts)), "lines": len(texts),
                    "mean_confidence": round(statistics.mean(scores), 6) if scores else None,
                    "low_confidence_lines": sum(score < 0.8 for score in scores),
                    **native_metrics(refs, texts, boxes, args.scale),
                }
                rows.append(row)
                print(json.dumps(row), flush=True)
                if args.private_predictions:
                    (args.output / f"private_{version}_{case['case_id']}.json").write_text(json.dumps({"texts": texts, "scores": scores, "boxes": boxes}, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output / "benchmark.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"render_scale": args.scale, "threads": 4, "network_blocked_during_inference": True, "model_sha256": provenance, "versions": {}}
    for version in args.versions:
        selected = [row for row in rows if row["version"] == version]
        native = [row for row in selected if row["native_reference_cjk"]]
        summary["versions"][version] = {
            "pages": len(selected), "median_seconds": statistics.median(row["seconds"] for row in selected),
            "total_seconds": round(sum(row["seconds"] for row in selected), 4),
            "native_control_pages": len(native),
            "native_cjk_reference_characters": sum(row["native_reference_cjk"] for row in native),
            "weighted_cjk_cer_proxy": round(sum(row["cjk_cer_proxy"] * row["native_reference_cjk"] for row in native) / max(sum(row["native_reference_cjk"] for row in native), 1), 6),
            "weighted_cjk_bag_recall": round(sum(row["cjk_bag_recall"] * row["native_reference_cjk"] for row in native) / max(sum(row["native_reference_cjk"] for row in native), 1), 6),
            "outlined_pages_have_no_gold_reference": True,
        }
    (args.output / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary["versions"]}), flush=True)


if __name__ == "__main__":
    main()
