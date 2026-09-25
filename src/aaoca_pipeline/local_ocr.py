"""Explicit, local-only OCR fallback for pages with an unusable text layer.

The ordinary pipeline does not import this module or load models unless OCR was
requested. Model acquisition is a separate command using public model assets;
inference requires all models to exist before any patient PDF is opened. No
patient content, raster page, text, or identifier is sent to a remote service.

OCR scores are model confidence, not calibrated clinical accuracy. Tables remain
lines with geometry; no unverified analyte/value pairing is asserted.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
MODEL_FILES = {
    "Det": "PP-OCRv6_det_small.onnx",
    "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "Rec": "PP-OCRv6_rec_small.onnx",
}
OCR_VERSION = "rapidocr_ppocrv6_cpu_v1"


class LocalOCREngine:
    """Persistent CPU engine with explicitly provided local ONNX models."""

    def __init__(self, model_dir: Path, *, threads: int = 4, render_scale: float = 2.0):
        model_dir = Path(model_dir).resolve()
        # Validate everything before constructing RapidOCR. This prevents its
        # normal missing-model downloader from being invoked during inference.
        missing = [name for name in MODEL_FILES.values() if not (model_dir / name).is_file()]
        if missing:
            raise FileNotFoundError("Local OCR models missing; run the separate download-models command first.")
        if render_scale <= 0 or threads < 1:
            raise ValueError("render_scale and threads must be positive")
        from rapidocr import RapidOCR

        self.render_scale = render_scale
        self.model_dir = model_dir
        self.engine = RapidOCR(params={
            "Global.log_level": "warning", "Global.use_cls": False,
            "Global.model_root_dir": str(model_dir),
            "EngineConfig.onnxruntime.intra_op_num_threads": threads,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            **{f"{kind}.model_path": str(model_dir / name) for kind, name in MODEL_FILES.items()},
        })
        self.provenance = {
            "method": OCR_VERSION, "rapidocr_version": importlib.metadata.version("rapidocr"),
            "onnxruntime_version": importlib.metadata.version("onnxruntime"),
            "render_scale": render_scale, "execution_provider": "CPUExecutionProvider",
            "model_sha256": {
                name: hashlib.sha256((model_dir / name).read_bytes()).hexdigest()
                for name in MODEL_FILES.values()
            },
        }

    def recognize(self, page: Any) -> dict[str, Any]:
        """Rasterize one page in memory; return raw OCR lines in page coordinates."""
        import fitz
        import numpy as np

        started = time.monotonic()
        pixmap = page.get_pixmap(matrix=fitz.Matrix(self.render_scale, self.render_scale), alpha=False)
        pixels = np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
        output = self.engine(pixels, use_cls=False)
        texts = list(output.txts) if output.txts is not None else []
        scores = [float(score) for score in output.scores] if output.scores is not None else []
        boxes = output.boxes.tolist() if output.boxes is not None else []
        lines = []
        for index, (text, score, box) in enumerate(zip(texts, scores, boxes)):
            points = [[round(float(x) / self.render_scale, 3), round(float(y) / self.render_scale, 3)] for x, y in box]
            lines.append({
                "line": index + 1, "text": text, "confidence": round(score, 6),
                "polygon": points,
                "bbox": [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)],
                "low_confidence": score < 0.8,
            })
        text = "\n".join(line["text"] for line in lines)
        return {
            "ocr_text": text, "ocr_lines": lines,
            "ocr_character_count": len(text),
            "ocr_mean_confidence": round(sum(scores) / len(scores), 6) if scores else None,
            "ocr_low_confidence_line_count": sum(line["low_confidence"] for line in lines),
            "ocr_status": "recovered_unverified" if text.strip() else "empty",
            "ocr_method": OCR_VERSION, "ocr_elapsed_seconds": round(time.monotonic() - started, 4),
            "ocr_raster_size": [pixmap.width, pixmap.height],
        }


def apply_local_ocr(
    source_pdf: Path, extracted: dict[str, Any], engine: LocalOCREngine, *, max_pages: int = 0,
) -> dict[str, Any]:
    """OCR only recommended pages, retaining both raw text and original status.

    ``max_pages=0`` means all recommended pages; a positive limit supports
    reproducible probes. Successful OCR remains ``partial`` until reviewed.
    A page with incomplete clinical text never silently becomes clean ``ok``.
    """
    import fitz

    if max_pages < 0:
        raise ValueError("max_pages must be nonnegative")
    result = copy.deepcopy(extracted)
    result["raw_parse_status"] = result["parse_status"]
    result["raw_page_status_counts"] = result.get("page_status_counts", {})
    result["ocr_provenance"] = engine.provenance
    attempted = recovered = 0
    if not any(page.get("ocr_recommended") for page in result.get("pages", [])):
        result.update(ocr_attempted_page_count=0, ocr_recovered_page_count=0, ocr_character_count=0, ocr_pending_page_count=0)
        return result
    with fitz.open(source_pdf) as document:
        for page_result in result.get("pages", []):
            if not page_result.get("ocr_recommended"):
                continue
            if max_pages and attempted >= max_pages:
                page_result["ocr_status"] = "not_attempted_page_limit"
                continue
            attempted += 1
            page_result["raw_extraction_status"] = page_result["extraction_status"]
            try:
                ocr = engine.recognize(document[page_result["page"] - 1])
                page_result.update(ocr)
                if ocr["ocr_text"].strip():
                    recovered += 1
                    page_result["analysis_text"] = ocr["ocr_text"]
                    page_result["analysis_text_source"] = "local_ocr"
                    page_result["extraction_status"] = "partial"
                    page_result["flags"] = sorted(set(page_result["flags"] + ["local_ocr_unverified"]))
                    if ocr["ocr_low_confidence_line_count"]:
                        page_result["flags"].append("ocr_low_confidence_lines")
            except Exception as error:
                page_result["ocr_status"] = "failed"
                page_result["ocr_error_type"] = type(error).__name__
                page_result["flags"] = sorted(set(page_result["flags"] + ["local_ocr_failed"]))
                LOGGER.warning("Local OCR failed: page=%d type=%s", page_result["page"], type(error).__name__)
            if attempted % 20 == 0:
                LOGGER.info("Local OCR page progress: attempted=%d recovered=%d", attempted, recovered)
    result["ocr_attempted_page_count"] = attempted
    result["ocr_recovered_page_count"] = recovered
    result["ocr_character_count"] = sum(page.get("ocr_character_count", 0) for page in result.get("pages", []))
    result["ocr_pending_page_count"] = sum(
        page.get("ocr_recommended", False) and page.get("ocr_status") != "recovered_unverified"
        for page in result.get("pages", [])
    )
    result["page_status_counts"] = dict(Counter(page["extraction_status"] for page in result.get("pages", [])))
    result["flags"] = sorted({flag for page in result.get("pages", []) for flag in page.get("flags", [])})
    if recovered:
        result["parse_status"] = "partial"
        result["flags"] = sorted(set(result["flags"] + ["local_ocr_unverified"]))
    return result


def download_models(model_dir: Path) -> dict[str, Any]:
    """Download PUBLIC model weights only. This command takes no patient input."""
    from rapidocr import RapidOCR

    model_dir = Path(model_dir).resolve()
    model_dir.mkdir(parents=True, exist_ok=True)
    RapidOCR(params={"Global.model_root_dir": str(model_dir), "Global.log_level": "warning"})
    engine = LocalOCREngine(model_dir)
    manifest = {**engine.provenance, "acquisition": "public model weights via RapidOCR downloader; no patient inputs"}
    (model_dir / "model_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    download = subparsers.add_parser("download-models", help="Download public model assets without opening any patient files")
    download.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "download-models":
        manifest = download_models(args.model_dir)
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
