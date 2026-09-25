"""Independent scoring of a frozen page-level Gold Set against any pipeline run."""
from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import math
from pathlib import Path
import re
import unicodedata

from .gold_common import (SCHEMA, annotation_digest, complete_run, digest,
                          load_annotations, read_json, source_documents)

SCORING_VERSION = "page_line_alignment_v1"
NUMBER_RE = re.compile(r"\d+(?:[./:-]\d+)*")


def _clean_text(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", value) if not ch.isspace())


def edit_distance(pattern: str, text: str) -> int:
    """Exact Levenshtein distance using Myers' arbitrary-width bit vectors."""
    if not pattern:
        return len(text)
    mask = (1 << len(pattern)) - 1
    high = 1 << (len(pattern) - 1)
    char_masks = {}
    for i, char in enumerate(pattern):
        char_masks[char] = char_masks.get(char, 0) | (1 << i)
    positive, negative, score = mask, 0, len(pattern)
    for char in text:
        equals = char_masks.get(char, 0)
        x = equals | negative
        d = (((equals & positive) + positive) ^ positive) | equals | negative
        hpos = negative | ~(d | positive)
        hneg = positive & d
        if hpos & high:
            score += 1
        elif hneg & high:
            score -= 1
        hpos = ((hpos << 1) | 1) & mask
        hneg = (hneg << 1) & mask
        positive = hneg | ~(x | hpos) & mask
        negative = hpos & d
    return score


def _align_lines(gold: list[str], pred: list[str]) -> dict[int, int]:
    """Monotonic one-to-one alignment; weakly matching lines remain unmapped."""
    n, m = len(gold), len(pred)
    matrix = [[0.0] * (m + 1) for _ in range(n + 1)]
    trace = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        matrix[i][0] = -0.35 * i
        trace[i][0] = 1
    for j in range(1, m + 1):
        matrix[0][j] = -0.35 * j
        trace[0][j] = 2
    for i in range(1, n + 1):
        a = _clean_text(gold[i - 1])
        for j in range(1, m + 1):
            b = _clean_text(pred[j - 1])
            similarity = SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0
            match = matrix[i - 1][j - 1] + (2 * similarity - 0.8 if similarity >= 0.45 else -1.0)
            delete = matrix[i - 1][j] - 0.35
            insert = matrix[i][j - 1] - 0.35
            best = max(match, delete, insert)
            matrix[i][j] = best
            trace[i][j] = 0 if best == match else 1 if best == delete else 2
    i, j, mapping = n, m, {}
    while i and j:
        move = trace[i][j]
        if move == 0:
            a, b = _clean_text(gold[i - 1]), _clean_text(pred[j - 1])
            if a and b and SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.45:
                mapping[j] = i
            i -= 1
            j -= 1
        elif move == 1:
            i -= 1
        else:
            j -= 1
    return mapping


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _f1(tp: int, fp: int, fn: int) -> float | None:
    denominator = 2 * tp + fp + fn
    return _ratio(2 * tp, denominator)


def _boundary_counts(gold: set[int], pred: list[int], tolerance: int) -> tuple[int, int, int]:
    available = set(gold)
    matched = 0
    for boundary in pred:
        match = min((x for x in available if abs(x - boundary) <= tolerance),
                    key=lambda x: (abs(x - boundary), x), default=None)
        if match is not None:
            available.remove(match)
            matched += 1
    return matched, len(pred) - matched, len(available)


def _date_role(source: str) -> str:
    if "test_timestamp_column" in source:
        return "test"
    if "title_timestamp" in source or source.startswith("explicit_field:") or source.startswith("local_ocr:explicit_field:"):
        return "document"
    return "unknown"


def _failure(unit: dict, metric: str, mode: str, gold_type: str = "", impact: str = "unknown", **detail) -> dict:
    return {"unit_id": unit["unit_id"], "source_sha256": unit["source_sha256"], "page": unit["page"],
            "stratum": unit["stratum"], "metric": metric, "mode": mode,
            "gold_type": gold_type, "clinical_impact": impact, **detail}


def _score_unit(unit: dict, annotation: dict, page: dict, predictions: list[dict]) -> tuple[Counter, list[dict], dict]:
    counts, failures, type_stats = Counter(), [], defaultdict(Counter)
    gold_lines = annotation["text"]["gold_text"].splitlines()
    pred_lines = page.get("normalized_text", "").splitlines()
    gold_sections = annotation["sections"]
    counts["pages_reviewed"] += 1
    if annotation["text"]["status"] != "uncertain":
        a, b = _clean_text(annotation["text"]["gold_text"]), _clean_text(page.get("normalized_text", ""))
        distance = edit_distance(a, b)
        counts.update(text_pages=1, text_reference_chars=len(a), text_edits=distance,
                      text_exact_pages=int(distance == 0))
        gold_numbers = Counter(NUMBER_RE.findall(a))
        pred_numbers = Counter(NUMBER_RE.findall(b))
        counts["numeric_gold_tokens"] += sum(gold_numbers.values())
        counts["numeric_recovered_tokens"] += sum((gold_numbers & pred_numbers).values())
        if distance:
            failures.append(_failure(unit, "text", "transcription_difference",
                                     impact=annotation["text"].get("impact", "unknown"), edits=distance,
                                     reference_chars=len(a)))
    else:
        counts["text_excluded_uncertain"] += 1
    if annotation["text"]["status"] == "uncertain":
        return counts, failures, {"unit_id": unit["unit_id"], "scored": False, "reason": "uncertain_text",
                                  "type_stats": {}}

    line_map = _align_lines(gold_lines, pred_lines)
    counts["gold_nonempty_lines"] += sum(bool(x.strip()) for x in gold_lines)
    counts["aligned_gold_lines"] += len(set(line_map.values()))
    gold_nonempty = [i for i, line in enumerate(gold_lines, 1) if line.strip()]
    pred_nonempty = [i for i, line in enumerate(pred_lines, 1) if line.strip()]
    gold_start = gold_nonempty[0] if gold_nonempty else math.inf
    pred_start = pred_nonempty[0] if pred_nonempty else math.inf
    gold_boundaries = {s["start_line"] for s in gold_sections if s["start_line"] > gold_start}
    pred_boundaries = []
    for section in predictions:
        if section["start_line"] > pred_start:
            pred_boundaries.append(line_map.get(section["start_line"], -section["start_line"]))
    for label, tolerance in (("boundary_exact", 0), ("boundary_tolerant", 1)):
        tp, fp, fn = _boundary_counts(gold_boundaries, pred_boundaries, tolerance)
        counts.update({label + "_tp": tp, label + "_fp": fp, label + "_fn": fn})
    if counts["boundary_tolerant_fn"]:
        failures.append(_failure(unit, "boundary", "missed_boundary", count=counts["boundary_tolerant_fn"]))
    if counts["boundary_tolerant_fp"]:
        failures.append(_failure(unit, "boundary", "extra_boundary", count=counts["boundary_tolerant_fp"]))

    gold_sets = [{i for i in range(s["start_line"], s["end_line"] + 1) if gold_lines[i - 1].strip()}
                 for s in gold_sections]
    pred_sets = [{line_map[i] for i in range(s["start_line"], s["end_line"] + 1) if i in line_map}
                 for s in predictions]
    edges = []
    for gi, gold_set in enumerate(gold_sets):
        for pi, pred_set in enumerate(pred_sets):
            union = gold_set | pred_set
            iou = len(gold_set & pred_set) / len(union) if union else 0.0
            if iou >= 0.5:
                edges.append((iou, gi, pi))
    matched_gold, matched_pred, matches = set(), set(), []
    for iou, gi, pi in sorted(edges, key=lambda x: (-x[0], x[1], x[2])):
        if gi not in matched_gold and pi not in matched_pred:
            matched_gold.add(gi)
            matched_pred.add(pi)
            matches.append((gi, pi, iou))
    counts["gold_sections"] += len(gold_sections)
    counts["pred_sections"] += len(predictions)
    counts["matched_sections"] += len(matches)
    counts["missed_sections"] += len(gold_sections) - len(matches)
    counts["extra_sections"] += len(predictions) - len(matches)
    counts["section_iou_milli_sum"] += round(sum(iou for _, _, iou in matches) * 1000)
    for gi, section in enumerate(gold_sections):
        if section["type"]["status"] == "known":
            type_stats[section["type"]["value"]]["gold_sections"] += 1
        if gi not in matched_gold:
            if section["type"]["status"] == "known":
                type_stats[section["type"]["value"]]["missed_sections"] += 1
            failures.append(_failure(unit, "section", "missed_section", section_index=gi + 1,
                                     gold_type=section["type"].get("value", ""), impact=section.get("impact", "unknown")))
    for pi in range(len(predictions)):
        if pi not in matched_pred:
            failures.append(_failure(unit, "section", "extra_section", prediction_index=pi + 1))
    for gi, pi, iou in matches:
        gold, pred = gold_sections[gi], predictions[pi]
        gtype = gold["type"].get("value", "") if gold["type"]["status"] == "known" else ""
        impact = gold.get("impact", "unknown")
        if gtype:
            type_stats[gtype]["matched_sections"] += 1
        if gold["type"]["status"] == "known":
            counts["type_evaluable"] += 1
            counts["type_correct"] += int(gtype == pred.get("section_type"))
            type_stats[gtype]["type_evaluable"] += 1
            type_stats[gtype]["type_correct"] += int(gtype == pred.get("section_type"))
            if gtype != pred.get("section_type"):
                failures.append(_failure(unit, "type", "wrong_type", gtype, impact,
                                         predicted=pred.get("section_type", ""), section_index=gi + 1))
        else:
            counts["type_excluded_" + gold["type"]["status"]] += 1
        if gold["subtype"]["status"] == "known":
            counts["subtype_evaluable"] += 1
            good = gold["subtype"].get("value", "") == pred.get("section_subtype", "")
            counts["subtype_correct"] += int(good)
            if gtype:
                type_stats[gtype]["subtype_evaluable"] += 1
                type_stats[gtype]["subtype_correct"] += int(good)
            if not good:
                failures.append(_failure(unit, "subtype", "wrong_subtype", gtype, impact,
                                         predicted=pred.get("section_subtype", ""), section_index=gi + 1))
        else:
            counts["subtype_excluded_" + gold["subtype"]["status"]] += 1
        dt = gold["date"]
        if dt["status"] in {"known", "absent"}:
            counts["date_evaluable"] += 1
            if gtype:
                type_stats[gtype]["date_evaluable"] += 1
            expected = dt.get("value", "") if dt["status"] == "known" else ""
            observed = pred.get("section_date", "")
            value_ok = expected == observed
            counts["date_value_correct"] += int(value_ok)
            if gtype:
                type_stats[gtype]["date_value_correct"] += int(value_ok)
            if not value_ok:
                distractor = next((x["role"] for x in dt.get("other_dates", []) if x["value"] == observed), "")
                if not observed:
                    mode = "missing_date"
                elif distractor:
                    mode = "date_confused_with_" + distractor
                elif not expected:
                    mode = "invented_date"
                else:
                    mode = "wrong_date"
                failures.append(_failure(unit, "date", mode, gtype, impact, section_index=gi + 1,
                                         expected=expected, predicted=observed))
            if dt["status"] == "known":
                counts["date_known"] += 1
                counts["date_known_correct"] += int(value_ok)
                counts["date_asserted"] += int(bool(observed) and not pred.get("date_uncertain", False))
                actual_role = _date_role(pred.get("date_source", ""))
                counts["date_role_correct"] += int(value_ok and actual_role == dt.get("role"))
                if value_ok and actual_role != dt.get("role"):
                    failures.append(_failure(unit, "date_role", "wrong_date_role", gtype, impact,
                                             section_index=gi + 1, predicted_role=actual_role,
                                             expected_role=dt.get("role")))
        else:
            counts["date_excluded_" + dt["status"]] += 1
    return counts, failures, {"unit_id": unit["unit_id"], "scored": True, "stratum": unit["stratum"],
                              "gold_sections": len(gold_sections), "matched_sections": len(matches),
                              "failure_count": len(failures),
                              "type_stats": {k: dict(v) for k, v in type_stats.items()}}


def _metrics(counts: Counter) -> dict:
    return {"pages_reviewed": counts["pages_reviewed"],
            "text_pages": counts["text_pages"],
            "text_cer": _ratio(counts["text_edits"], counts["text_reference_chars"]),
            "text_exact_page_rate": _ratio(counts["text_exact_pages"], counts["text_pages"]),
            "numeric_token_recall": _ratio(counts["numeric_recovered_tokens"], counts["numeric_gold_tokens"]),
            "line_alignment_rate": _ratio(counts["aligned_gold_lines"], counts["gold_nonempty_lines"]),
            "boundary_exact_f1": _f1(counts["boundary_exact_tp"], counts["boundary_exact_fp"], counts["boundary_exact_fn"]),
            "boundary_tolerant_f1": _f1(counts["boundary_tolerant_tp"], counts["boundary_tolerant_fp"], counts["boundary_tolerant_fn"]),
            "section_match_recall": _ratio(counts["matched_sections"], counts["gold_sections"]),
            "section_match_precision": _ratio(counts["matched_sections"], counts["pred_sections"]),
            "matched_mean_iou": _ratio(counts["section_iou_milli_sum"], counts["matched_sections"] * 1000),
            "type_accuracy_matched": _ratio(counts["type_correct"], counts["type_evaluable"]),
            "subtype_accuracy_matched": _ratio(counts["subtype_correct"], counts["subtype_evaluable"]),
            "date_value_accuracy_matched": _ratio(counts["date_value_correct"], counts["date_evaluable"]),
            "date_value_accuracy_known": _ratio(counts["date_known_correct"], counts["date_known"]),
            "date_assertion_rate_known": _ratio(counts["date_asserted"], counts["date_known"]),
            "date_value_and_role_accuracy_known": _ratio(counts["date_role_correct"], counts["date_known"]),
            "counts": dict(sorted(counts.items()))}


def evaluate(gold_dir: Path, revision: str, output: Path) -> dict:
    manifest, annotations = load_annotations(gold_dir, revision)
    receipt = read_json(gold_dir / "revisions" / revision / "freeze.json")
    if receipt.get("sample_id") != manifest["sample_id"] or receipt.get("annotation_schema") != SCHEMA or receipt.get("annotation_digest") != annotation_digest(annotations):
        raise ValueError("Frozen annotation digest does not match its receipt")
    if len(annotations) != len(manifest["units"]):
        raise ValueError("Frozen annotation set is incomplete")
    metadata = complete_run(output)
    docs = source_documents(output)
    needed = {u["source_sha256"] for u in manifest["units"]}
    missing = needed - docs.keys()
    if missing:
        raise ValueError(f"Pipeline output lacks {len(missing)} sampled source PDFs")
    cache = {}
    all_counts, failures, unit_scores = Counter(), [], []
    by_baseline_source = defaultdict(Counter)
    by_evaluated_source = defaultdict(Counter)
    by_type = defaultdict(Counter)
    for unit in manifest["units"]:
        sha = unit["source_sha256"]
        doc = docs[sha]
        if sha not in cache:
            norm_path = output / doc["text_path"].replace(".txt", ".json")
            cache[sha] = (read_json(norm_path), read_json(output / doc["sections_path"]))
        normalized, sections = cache[sha]
        page = next((p for p in normalized["pages"] if p["page"] == unit["page"]), None)
        if page is None:
            raise ValueError(f"Pipeline output lacks sampled page {unit['unit_id']}")
        predictions = []
        for section in sections["sections"]:
            span = next((s for s in section["page_spans"] if s["page"] == unit["page"]), None)
            if span:
                predictions.append({**section, "start_line": span["start_line"], "end_line": span["end_line"]})
        annotation = annotations[unit["unit_id"]]
        if annotation["status"] == "unreviewable":
            all_counts["pages_unreviewable"] += 1
            by_baseline_source[unit["stratum"].split("_")[0]]["pages_unreviewable"] += 1
            unit_scores.append({"unit_id": unit["unit_id"], "scored": False, "reason": "unreviewable"})
            continue
        counts, page_failures, score = _score_unit(unit, annotation, page, predictions)
        all_counts.update(counts)
        by_baseline_source[unit["stratum"].split("_")[0]].update(counts)
        evaluated_source = "ocr" if page.get("analysis_text_source") == "local_ocr" else "native"
        by_evaluated_source[evaluated_source].update(counts)
        score["evaluated_text_source"] = evaluated_source
        for kind, stats in score["type_stats"].items():
            by_type[kind].update(stats)
        for failure in page_failures:
            if failure["gold_type"]:
                by_type[failure["gold_type"]][failure["mode"]] += failure.get("count", 1)
        failures.extend(page_failures)
        unit_scores.append(score)
    mode_counts = Counter()
    for failure in failures:
        mode_counts[failure["mode"]] += failure.get("count", 1)
    return {"scoring_version": SCORING_VERSION, "sample_id": manifest["sample_id"],
            "sample_schema": manifest["schema_version"], "annotation_revision": revision,
            "annotation_schema": SCHEMA, "annotation_digest": receipt["annotation_digest"],
            "pipeline": {"version": metadata["pipeline_version"], "run_id": metadata["run_id"],
                         "code_sha256": metadata["code_sha256"],
                         "run_metadata_sha256": hashlib.sha256((output / "run_metadata.json").read_bytes()).hexdigest()},
            "metrics": _metrics(all_counts),
            "by_baseline_text_source": {k: _metrics(v) for k, v in sorted(by_baseline_source.items())},
            "by_evaluated_text_source": {k: _metrics(v) for k, v in sorted(by_evaluated_source.items())},
            "by_gold_type": {k: {**dict(sorted(v.items())),
                                 "section_match_recall": _ratio(v["matched_sections"], v["gold_sections"]),
                                 "type_accuracy_matched": _ratio(v["type_correct"], v["type_evaluable"]),
                                 "subtype_accuracy_matched": _ratio(v["subtype_correct"], v["subtype_evaluable"]),
                                 "date_value_accuracy_matched": _ratio(v["date_value_correct"], v["date_evaluable"])}
                             for k, v in sorted(by_type.items())},
            "failure_modes": dict(mode_counts.most_common()),
            "high_impact_failures": sum(f["clinical_impact"] == "high" for f in failures),
            "unit_scores": unit_scores, "failures": failures}


def compare(left: dict, right: dict) -> dict:
    keys = ("scoring_version", "sample_id", "sample_schema", "annotation_revision",
            "annotation_schema", "annotation_digest")
    if any(left.get(k) != right.get(k) for k in keys):
        raise ValueError("Both evaluations must use the same frozen benchmark and scorer")
    left_units = {x["unit_id"]: x["scored"] for x in left["unit_scores"]}
    right_units = {x["unit_id"]: x["scored"] for x in right["unit_scores"]}
    if left_units != right_units:
        raise ValueError("Evaluations scored different page sets")
    fields = ("text_cer", "numeric_token_recall", "boundary_exact_f1", "boundary_tolerant_f1",
              "section_match_recall", "section_match_precision", "type_accuracy_matched",
              "subtype_accuracy_matched", "date_value_accuracy_matched", "date_value_accuracy_known",
              "date_value_and_role_accuracy_known")
    delta = {}
    for field in fields:
        a, b = left["metrics"][field], right["metrics"][field]
        delta[field] = round(b - a, 6) if a is not None and b is not None else None
    def failure_keys(report):
        return {(f["unit_id"], f["metric"], f["mode"]) for f in report["failures"]}
    before, after = failure_keys(left), failure_keys(right)
    return {"sample_id": left["sample_id"], "annotation_revision": left["annotation_revision"],
            "annotation_digest": left["annotation_digest"], "scoring_version": left["scoring_version"],
            "left_run": left["pipeline"], "right_run": right["pipeline"], "delta_right_minus_left": delta,
            "resolved_failure_keys": sorted(before - after), "new_failure_keys": sorted(after - before),
            "left_metrics": left["metrics"], "right_metrics": right["metrics"]}
