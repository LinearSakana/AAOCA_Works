"""Resumable local OCR execution using independent Windows-safe processes.

PyMuPDF documents are never shared across threads/processes. A worker loads its
own PDF and ONNX session. Completed document OCR is atomically cached; reruns
only schedule missing cache entries. Native extraction caches stay untouched.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import inspect
import json
import logging
from pathlib import Path

from .io_utils import write_json

LOGGER = logging.getLogger("aaoca_pipeline")
_ENGINE = None


def _initialize(model_dir: str, threads: int, scale: float) -> None:
    global _ENGINE
    from .local_ocr import LocalOCREngine
    _ENGINE = LocalOCREngine(Path(model_dir), threads=threads, render_scale=scale)


def _run_one(job: dict) -> dict:
    from .local_ocr import apply_local_ocr
    extracted = json.loads(Path(job["raw_cache"]).read_text(encoding="utf-8"))
    result = apply_local_ocr(Path(job["source_pdf"]), extracted, _ENGINE, max_pages=job["max_pages"])
    result["ocr_cache_fingerprint"] = job["fingerprint"]
    result["ocr_source_sha256"] = job["sha256"]
    write_json(Path(job["target"]), result)
    return {"sha256": job["sha256"], "target": job["target"],
            "attempted": result.get("ocr_attempted_page_count", 0),
            "recovered": result.get("ocr_recovered_page_count", 0)}


def prepare_ocr(files: list[dict], extracted_by_sha: dict, cache: Path, extraction_fingerprint: str,
                settings: dict) -> tuple[dict[str, Path], dict]:
    """Validate local model files before scheduling, never download at runtime."""
    from .local_ocr import LocalOCREngine
    model_dir = Path(settings["ocr_model_dir"])
    workers = int(settings.get("ocr_workers", 4))
    threads = int(settings.get("ocr_threads", 2))
    scale = float(settings.get("ocr_render_scale", 2.0))
    max_pages = int(settings.get("ocr_max_pages", 0))
    if workers < 1 or threads < 1 or max_pages < 0:
        raise ValueError("OCR workers/threads must be positive and page limit nonnegative")
    # One local engine provides validated model hashes and software provenance.
    probe = LocalOCREngine(model_dir, threads=threads, render_scale=scale)
    provenance = probe.provenance
    version = {"models": provenance, "max_pages": max_pages,
               "recognizer_code": hashlib.sha256(inspect.getsource(LocalOCREngine.recognize).encode()).hexdigest(),
               "extraction_fingerprint": extraction_fingerprint}
    fingerprint = hashlib.sha256(json.dumps(version, sort_keys=True).encode()).hexdigest()[:20]
    del probe
    paths, jobs, seen = {}, [], set()
    hits = planned_pages = 0
    for file_record in files:
        sha = file_record.get("content_key") or file_record["sha256"]
        if sha in seen:
            continue
        seen.add(sha)
        data = extracted_by_sha[sha]
        recommended = data.get("ocr_recommended_page_count", 0)
        if not recommended or not data.get("pages"):
            continue
        target = cache / "local_ocr" / fingerprint / f"{sha}.json"
        paths[sha] = target
        planned_pages += min(recommended, max_pages) if max_pages else recommended
        if target.exists():
            try:
                previous = json.loads(target.read_text(encoding="utf-8"))
                if previous.get("ocr_source_sha256") == sha and previous.get("ocr_cache_fingerprint") == fingerprint:
                    hits += 1
                    continue
            except (ValueError, OSError):
                pass
        jobs.append({"sha256": sha, "source_pdf": file_record["source_pdf"],
                     "raw_cache": str(cache / extraction_fingerprint / f"{sha}.json"),
                     "target": str(target), "max_pages": max_pages, "fingerprint": fingerprint})
    LOGGER.info("Local OCR: documents=%s cached=%s queued=%s planned pages=%s workers=%s", len(paths), hits, len(jobs), planned_pages, workers)
    if jobs:
        with ProcessPoolExecutor(max_workers=workers, initializer=_initialize,
                                 initargs=(str(model_dir), threads, scale)) as pool:
            pending = {pool.submit(_run_one, job): job for job in jobs}
            completed = recovered = attempted = 0
            while pending:
                done, _ = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
                for future in done:
                    job = pending.pop(future)
                    result = future.result()
                    completed += 1
                    recovered += result["recovered"]
                    attempted += result["attempted"]
                    LOGGER.info("Local OCR completed %s/%s documents; newly attempted=%s recovered=%s", completed, len(jobs), attempted, recovered)
                if not done:
                    LOGGER.info("Local OCR working: completed=%s/%s pending=%s; completed documents are cached", completed, len(jobs), len(pending))
    return paths, {"fingerprint": fingerprint, "provenance": provenance, "documents": len(paths),
                   "cache_hits": hits, "planned_pages": planned_pages, "workers": workers, "threads_per_worker": threads}
