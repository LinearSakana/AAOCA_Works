"""Sample, review, freeze and evaluate the local AAOCA PDF Gold Set.

Run `python -X utf8 scripts/gold_set.py --help` for commands. Patient text and
evaluation failure rows remain under the Git-ignored data directory.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aaoca_pipeline.gold_common import freeze, load_annotations, sample, write_json
from aaoca_pipeline.gold_evaluate import compare, evaluate
from aaoca_pipeline.gold_review import serve


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sampling = sub.add_parser("sample", help="Create a fixed stratified PDF-page sample")
    sampling.add_argument("--run", type=Path, required=True)
    sampling.add_argument("--gold-dir", type=Path, required=True)
    sampling.add_argument("--pages-per-stratum", type=int, default=12)
    sampling.add_argument("--seed", type=int, default=20260925)
    review = sub.add_parser("review", help="Start the loopback-only human review desk")
    review.add_argument("--run", type=Path, required=True)
    review.add_argument("--gold-dir", type=Path, required=True)
    review.add_argument("--port", type=int, default=8765)
    validation = sub.add_parser("validate", help="Validate saved working annotations")
    validation.add_argument("--gold-dir", type=Path, required=True)
    freezing = sub.add_parser("freeze", help="Create an immutable named annotation revision")
    freezing.add_argument("--gold-dir", type=Path, required=True)
    freezing.add_argument("--revision", required=True)
    scoring = sub.add_parser("evaluate", help="Score a complete pipeline run against a frozen revision")
    scoring.add_argument("--run", type=Path, required=True)
    scoring.add_argument("--gold-dir", type=Path, required=True)
    scoring.add_argument("--revision", required=True)
    scoring.add_argument("--report", type=Path, required=True)
    comparison = sub.add_parser("compare", help="Compare two reports on the identical Gold Set")
    comparison.add_argument("--left", type=Path, required=True)
    comparison.add_argument("--right", type=Path, required=True)
    comparison.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "sample":
        if args.pages_per_stratum < 1:
            parser.error("--pages-per-stratum must be positive")
        result = sample(args.run, args.gold_dir, args.pages_per_stratum, args.seed)
        print(json.dumps({"sample_id": result["sample_id"], "pages": len(result["units"]),
                          "strata": {key: sum(u["stratum"] == key for u in result["units"])
                                     for key in ("native_record", "native_lab", "ocr_record", "ocr_lab")}}, indent=2))
    elif args.command == "review":
        serve(args.gold_dir, args.run, args.port)
    elif args.command == "validate":
        manifest, annotations = load_annotations(args.gold_dir)
        statuses = {state: sum(a["status"] == state for a in annotations.values())
                    for state in ("draft", "complete", "unreviewable")}
        print(json.dumps({"sample_id": manifest["sample_id"], "sampled_pages": len(manifest["units"]),
                          "saved_pages": len(annotations), "missing_pages": len(manifest["units"]) - len(annotations),
                          "statuses": statuses}, indent=2))
    elif args.command == "freeze":
        print(json.dumps(freeze(args.gold_dir, args.revision), ensure_ascii=False, indent=2))
    elif args.command == "evaluate":
        result = evaluate(args.gold_dir, args.revision, args.run)
        write_json(args.report, result)
        print(json.dumps({"report": str(args.report), "pipeline": result["pipeline"],
                          "metrics": result["metrics"], "failure_modes": result["failure_modes"]},
                         ensure_ascii=False, indent=2))
    elif args.command == "compare":
        result = compare(json.loads(args.left.read_text(encoding="utf-8")),
                         json.loads(args.right.read_text(encoding="utf-8")))
        write_json(args.report, result)
        print(json.dumps({"report": str(args.report), "delta_right_minus_left": result["delta_right_minus_left"],
                          "resolved_failures": len(result["resolved_failure_keys"]),
                          "new_failures": len(result["new_failure_keys"])}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
